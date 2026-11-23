"""Explicit Qt native suite. Run only through the private-desktop child wrapper.

Not auto-discovered by the Tk-only build environment. Every case is mandatory
when selected; missing PySide6, a native plugin or isolation is a failure.
"""
import json
import os
from pathlib import Path
import sys
import threading
import tempfile
import time
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest

from qt_test_guard import install_qt_test_scope
from src.models.workbench_presentation import LogView
from src.ui.qt.demo_data import logs, projects
from src.ui.qt.main_window import MainWindow
from src.ui.qt.theme import GAP, apply_theme
from src.ui.qt.workspace_controller import WorkspaceController
from scripts.gui_test_process import run_gui_child


class QtNativeGuardTests(unittest.TestCase):
    def test_existing_workspace_receives_open_request_without_second_gui(self):
        from src.ui.qt.application import run_workspace, runtime_root
        with patch('src.core.workspace_instance.WorkspaceInstance') as lease:
            lease.return_value.start.return_value = False
            self.assertEqual(run_workspace('project.linecheck.json'), 0)
            lease.return_value.start.assert_called_once_with('project.linecheck.json')
            lease.return_value.close.assert_called_once()
        portable = Path(__file__).resolve().parent / '测试便携目录'
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(portable / 'DUTPilot.exe')), \
             patch.object(sys, '_MEIPASS', str(portable / 'bundled'), create=True):
            self.assertEqual(runtime_root(), portable)

    def test_native_adapter_rejects_missing_scope_wrong_thread_and_dialog(self):
        for mode, reason in (('missing', 'missing QtTestScope'), ('thread', 'GUI main thread'),
                             ('dialog', 'Unadapted native Qt dialog'), ('tkinter', 'imported tkinter'),
                             ('_tkinter', 'imported _tkinter')):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(AssertionError, reason):
                    run_gui_child([sys.executable, 'tests/fixtures/qt_guard_probe.py', mode],
                        native_render=True, framework='qt', timeout=20,
                        capture_output=True, text=True, encoding='utf-8')

    def test_native_adapter_maps_real_windows_widget(self):
        result = run_gui_child([sys.executable, 'tests/fixtures/qt_guard_probe.py', 'managed'],
            native_render=True, framework='qt', timeout=20, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.offscreen_report['qt']['platform'], 'windows')
        self.assertEqual(result.offscreen_report['qt']['managed_windows'], 1)

    def test_qt_repairs_restart_only_after_worker_and_single_instance_are_closed(self):
        from src.ui.qt.application import run_workspace, runtime_root

        order = []
        arguments = ['run_dutpilot_qt.py', '--gateway-slot', '3']
        with patch.object(sys, 'argv', arguments), \
                patch('src.core.workspace_instance.WorkspaceInstance') as instance, \
                patch('src.ui.qt.application._create_application') as create_app, \
                patch('src.ui.qt.application.MainWindow'), \
                patch('src.ui.qt.workspace_controller.WorkspaceController') as workspace, \
                patch('src.core.source_restart.launch_restart_helper') as restart:
            create_app.return_value.exec.side_effect = lambda: order.append('gui') or 0
            workspace.return_value.feishu_repair.restart_requested = True
            workspace.return_value.adapter.wait_closed.side_effect = lambda _: order.append('worker') or True
            instance.return_value.close.side_effect = lambda: order.append('instance')
            restart.side_effect = lambda *args, **kwargs: order.append('restart')
            self.assertEqual(run_workspace(), 0)
        self.assertEqual(order, ['gui', 'worker', 'instance', 'restart'])
        restart.assert_called_once_with(runtime_root(), tuple(arguments[1:]), cwd=os.getcwd())


class ComponentShowcaseTests(unittest.TestCase):
    def test_progress_animation_reuses_transitions_and_stops_when_hidden(self):
        from PySide6.QtCore import QAbstractAnimation, QPropertyAnimation
        from src.ui.qt.component_showcase import ComponentShowcase

        scope = install_qt_test_scope(self)
        page = ComponentShowcase()
        page.show()
        scope.app.processEvents()
        for widget in (page.progress_bar, page.circular_progress):
            widget.set_progress(0, animate=False)
            animation, = widget.findChildren(QPropertyAnimation)
            starts = []
            animation.stateChanged.connect(
                lambda new, old, events=starts: events.append(new) if new == QAbstractAnimation.State.Running else None)
            widget.set_progress(80)
            animation.setCurrentTime(animation.duration() // 2)
            intermediate = widget.paintedProgress
            self.assertGreater(intermediate, 0.)
            self.assertLess(intermediate, 80.)
            for _ in range(200):
                widget.set_progress(80)
            self.assertEqual(len(starts), 1)
            widget.set_progress(25, 'warning')
            self.assertAlmostEqual(widget.paintedProgress, intermediate)
            self.assertEqual(len(starts), 2)
            widget.hide()
            self.assertFalse(widget.is_animating)
            self.assertEqual(widget.paintedProgress, 25.)
            widget.set_progress(19)
            self.assertFalse(widget.is_animating)
            self.assertEqual(widget.paintedProgress, 19.)
            widget.show()
            widget.set_progress(95)
            widget.set_progress(None, 'unavailable')
            self.assertFalse(widget.is_animating)
            self.assertEqual(widget.paintedProgress, 0.)
            self.assertEqual(widget.display_text, '未接入')
        page.close()

    def test_component_showcase_progress_states_controls_and_native_layout(self):
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QIcon
        from src.ui.qt.component_showcase import ComponentShowcase
        from src.ui.qt.theme import V13_PALETTE

        scope = install_qt_test_scope(self)
        app = scope.app
        apply_theme(app)
        page = ComponentShowcase()
        page.resize(1100, 800)
        page.show()
        QTest.qWait(50)
        self.assertTrue(page.project_cards.model().rowCount())
        self.assertGreaterEqual(len(page.badges), 8)
        self.assertTrue(page.refresh_action.accessibleName())
        icon = page.refresh_action.icon()
        for mode, state, expected in (
            (QIcon.Mode.Normal, QIcon.State.Off, V13_PALETTE.brand),
            (QIcon.Mode.Active, QIcon.State.Off, V13_PALETTE.hover),
            (QIcon.Mode.Selected, QIcon.State.Off, V13_PALETTE.selected),
            (QIcon.Mode.Normal, QIcon.State.On, V13_PALETTE.selected),
            (QIcon.Mode.Disabled, QIcon.State.On, V13_PALETTE.disabled),
            (QIcon.Mode.Disabled, QIcon.State.Off, V13_PALETTE.disabled),
        ):
            sample = icon.pixmap(QSize(32, 32), mode, state).toImage()
            colors = (sample.pixelColor(x, y) for y in range(sample.height()) for x in range(sample.width()))
            self.assertIn(expected.lower(), {color.name() for color in colors if color.alpha() == 255}, (mode, state))
        for state, value, expected in (('normal', 0, '0%'), ('warning', 47, '47%'),
                                       ('error', 100, '100%'), ('unknown', None, '未知'),
                                       ('unavailable', None, '未接入')):
            page.progress_state.setCurrentIndex(page.progress_state.findData(state))
            if value is not None:
                page.progress_slider.setValue(value)
            self.assertEqual(page.primary_action.isEnabled(), value is not None)
            for widget in (page.progress_bar, page.circular_progress):
                self.assertEqual(widget.value, value)
                self.assertEqual(widget.state, state)
                self.assertEqual(widget.display_text, expected)
                if value is None:
                    self.assertFalse(widget.is_animating)
        page.progress_state.setCurrentIndex(page.progress_state.findData('normal'))
        page.progress_slider.setValue(63)
        page.progress_slider.setFocus()
        QTest.keyClick(page.progress_slider, Qt.Key_Right)
        QTest.qWait(400)
        for widget in (page.progress_bar, page.circular_progress):
            self.assertEqual(widget.display_text, '64%')
            self.assertEqual(widget.paintedProgress, 64.)
            self.assertFalse(widget.is_animating)
        page.primary_action.click()
        self.assertTrue(page.confirm_dialog.isVisible())
        page.confirm_dialog.reject()
        rejected = page.action_feedback.text()
        page.primary_action.click()
        page.confirm_dialog.accept()
        self.assertNotEqual(rejected, page.action_feedback.text())
        page.view_state.setCurrentIndex(page.view_state.findData('empty'))
        empty = page.state_stack.currentWidget()
        page.view_state.setCurrentIndex(page.view_state.findData('loading'))
        self.assertIsNot(empty, page.state_stack.currentWidget())
        page.channel_matrix.tiles[-1].click()
        self.assertIn('CH07', page.channel_feedback.text())
        page.log_panel.search.setText('校验超时')
        displayed = page.log_panel.text.toPlainText().splitlines()
        self.assertEqual(len(displayed), 1)
        self.assertIn('校验超时', displayed[0])
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        for width, height in ((1100, 800), (740, 580)):
            page.resize(width, height)
            page.scroll_area.verticalScrollBar().setValue(0)
            app.processEvents()
            self.assertEqual(page.width(), width)
            self.assertEqual(page.scroll_area.horizontalScrollBar().maximum(), 0)
            self.assertTrue(page.scroll_area.verticalScrollBar().maximum())
            if output:
                self.assertTrue(page.grab().save(str(Path(output) / f'component-showcase-{width}.png')))
        page.close()


class QtWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.scope = install_qt_test_scope(self)
        self.app = self.scope.app
        apply_theme(self.app)
        self.window = MainWindow(projects(), logs())
        self.window.resize(1480, 900)
        self.window.show()
        QTest.qWait(30)

    def test_form_wheel_scrolls_without_editing_values(self):
        from PySide6.QtWidgets import (QComboBox, QDialog, QScrollArea, QSpinBox, QStyle,
                                       QStyleOptionSpinBox, QVBoxLayout, QWidget)
        from src.ui.qt.application import FormWheelFilter

        wheel_filter = FormWheelFilter(self.app)
        self.app.installEventFilter(wheel_filter)
        self.addCleanup(self.app.removeEventFilter, wheel_filter)
        dialog = QDialog(self.window)
        area = QScrollArea()
        QVBoxLayout(dialog).addWidget(area)
        content = QWidget()
        form = QVBoxLayout(content)
        area.setWidget(content)
        area.setWidgetResizable(True)
        changes = []
        combos = []
        for editable in (False, True):
            combo = QComboBox()
            combo.setEditable(editable)
            combo.addItems([str(i) for i in range(80)])
            combo.setCurrentIndex(4)
            combo.currentTextChanged.connect(changes.append)
            combos.append(combo)
            form.addWidget(combo)
        spin = QSpinBox()
        spin.setValue(4)
        spin.valueChanged.connect(changes.append)
        form.addWidget(spin)
        form.addSpacing(1000)
        dialog.resize(320, 350)
        dialog.show()
        QTest.qWait(30)

        def wheel(widget, delta):
            window = widget.window()
            point = widget.mapTo(window, widget.rect().center())
            QTest.wheelEvent(window.windowHandle(), point, QPoint(0, delta))
            self.app.processEvents()

        bar = area.verticalScrollBar()
        for field in (*combos, spin):
            for focus in (area, field):
                focus.setFocus()
                bar.setValue(0)
                wheel(field, -120)
                self.assertGreater(bar.value(), 0)
                bar.setValue(1)
                wheel(field, 120)
                self.assertEqual(bar.value(), 0)
                self.assertEqual(changes, [])
        combo = combos[1]
        combo.showPopup()
        self.app.processEvents()
        view = combo.view()
        before = view.verticalScrollBar().value()
        wheel(view.viewport(), -120)
        self.assertGreater(view.verticalScrollBar().value(), before)
        self.assertEqual(combo.currentIndex(), 4)
        self.assertEqual(changes, [])
        index = view.indexAt(view.viewport().rect().center())
        self.assertTrue(index.isValid())
        point = view.visualRect(index).center()
        QTest.mouseMove(view.viewport(), point)
        QTest.qWait(self.app.doubleClickInterval() + 10)
        QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=point)
        self.assertEqual(combo.currentIndex(), index.row())
        QTest.keyClick(spin, Qt.Key_Up)
        self.assertEqual(spin.value(), 5)
        option = QStyleOptionSpinBox()
        spin.initStyleOption(option)
        arrow = spin.style().subControlRect(QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxUp, spin)
        QTest.mouseClick(spin, Qt.LeftButton, pos=arrow.center())
        self.assertEqual(spin.value(), 6)

    def test_qt_monitor_confirms_only_checked_project_channels(self):
        from src.models.qt_ai_chat import ChatWorkspaceView
        from src.ui.qt.ai_chat_dialog import AiChatDialog

        dialog = AiChatDialog(self.window.projects[0], self.window)
        dialog.show_view(ChatWorkspaceView((), '', ()))
        dialog.set_busy(False)
        dialog.show()
        submitted = []
        dialog.action_requested.connect(lambda op, args: submitted.append((op, args)))
        dialog.monitor_action.trigger()
        self.assertEqual(submitted.pop(), ('ai_chat_monitor_settings', ()))
        dialog.show_monitor(dict(token='fixture', model='fixture', provider='fixture',
            permission='ask', targets=[(2, 'CH2'), (7, 'CH7')], active=[], policy=dict(features=['ping']),
            status=dict(enabled=False, queued=0, running=0, cleaning=0, waiting_approval=0)))
        panel = dialog.monitor_dialog
        panel.channels.item(1).setCheckState(Qt.Checked)
        panel.automatic.setChecked(True)
        panel.threshold.setValue(5)
        panel.keywords.setText('断流;超时')
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            self.app.processEvents()
            self.assertTrue(panel.grab().save(str(Path(output) / 'qt-channel-diagnostics.png')))
        QTest.mouseClick(panel.apply_button, Qt.LeftButton)
        self.assertEqual(submitted, [('ai_chat_monitor_apply',
            ('fixture', (7,), ('ping',), 5, 60, ('断流', '超时'), (), True, 'ask'))])
        from PySide6.QtWidgets import QPushButton
        dialog.review_action_result('', dict(id='pending-monitor', name='read_dut_state', fingerprint='fixture',
            target=dict(channel=7, vlan='vlan107', port='COM7', bind_ip='192.0.2.7', host='192.0.2.1', telnet_port=23),
            params=dict(category='system'), assessment=dict(reason='模拟首次登录')), monitor=True)
        review = dialog.review_dialog
        self.assertIn('确认监控操作', review.windowTitle())
        reject = next(b for b in review.findChildren(QPushButton) if b.text() == '拒绝')
        QTest.mouseClick(reject, Qt.LeftButton)
        self.assertEqual(submitted[-1], ('ai_chat_monitor_decide', ('pending-monitor', 'fixture', False)))
        dialog.close()

    def test_qt_chat_formats_markdown_preserves_selection_and_uses_original_shortcuts(self):
        from dataclasses import replace
        from PySide6.QtGui import QFont, QTextCursor
        from src.models.qt_ai_chat import ChatMessageView, ChatSessionView, ChatWorkspaceView
        from src.ui.qt.ai_chat_dialog import AiChatDialog

        dialog = AiChatDialog(self.window.projects[0], self.window)
        session = ChatSessionView('fixture', '合成排查', '普通问答', '合成模型', '等待')
        stamp = '2026-11-20T23:58:00'
        markdown = ('# 诊断标题\n**保留强调**与 `vlan107`\n- 列表示例\n'
                    '```text\n  合成代码 **保持原样**\n```\n[外部地址](https://example.test)\n<img src="local.png">')
        messages = (
            ChatMessageView('user', '最早保留选区 **用户原文**', stamp, 'text'),
            ChatMessageView('assistant', markdown, stamp, 'text'),
            *(ChatMessageView('user', f'合成历史行 {n}', stamp, 'text') for n in range(36)),
        )
        state = ChatMessageView('system', '当前会话状态', stamp, 'text')
        view = ChatWorkspaceView((session,), 'fixture', messages + (state,), writable=True, latest_status=state)
        dialog.show_view(view)
        dialog.set_busy(False)
        dialog.show()
        self.app.processEvents()
        transcript = dialog.transcript
        shown = transcript.toPlainText()
        self.assertIn('诊断标题', shown)
        self.assertNotIn('# 诊断标题', shown)
        self.assertIn('**用户原文**', shown)
        self.assertIn('  合成代码 **保持原样**', shown)
        self.assertIn('[外部地址](https://example.test)', shown)
        self.assertIn('<img src="local.png">', shown)
        self.assertNotIn('当前会话状态', shown)
        self.assertIn('当前会话状态', dialog.latest_status.text())
        document = transcript.document()
        self.assertEqual(document.find('保留强调').charFormat().fontWeight(), QFont.Weight.Bold)
        self.assertIn('Consolas', document.find('vlan107').charFormat().fontFamilies())
        self.assertFalse(document.find('外部地址').charFormat().isAnchor())
        selected = document.find('最早保留选区')
        transcript.setTextCursor(selected)
        scroll = transcript.verticalScrollBar()
        scroll.setValue(scroll.maximum() // 3)
        position = scroll.value()
        self.assertGreater(position, 0)
        delta = []
        document.contentsChange.connect(lambda start, *_: delta.append(start))
        updated_state = replace(state, text='只更新当前状态')
        dialog.show_view(replace(view, latest_status=updated_state))
        self.assertFalse(delta)
        for draft in ('```text\n未关闭', '```text\n已关闭的流式代码\n```'):
            dialog.show_view(replace(view, draft=draft, running=True, latest_status=updated_state))
            self.assertEqual(transcript.textCursor().selectedText(), '最早保留选区')
            self.assertEqual(scroll.value(), position)
        self.assertFalse('```' in transcript.toPlainText())
        self.assertTrue(delta and min(delta) >= selected.selectionEnd())
        final = ChatMessageView('assistant', '最终 **合成结论**', stamp, 'text')
        dialog.show_view(replace(view, messages=view.messages + (final,), latest_status=updated_state))
        self.assertEqual(transcript.textCursor().selectedText(), '最早保留选区')
        self.assertNotIn('流式代码', transcript.toPlainText())
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            scroll.setValue(0)
            self.assertTrue(dialog.grab().save(str(Path(output) / 'ai-chat-formatted-transcript.png')))

        actions = []
        dialog.action_requested.connect(lambda operation, args: actions.append((operation, args)))
        dialog.composer.setPlainText('第一行')
        dialog.composer.moveCursor(QTextCursor.MoveOperation.End)
        QTest.keyClick(dialog.composer, Qt.Key.Key_Return, Qt.KeyboardModifier.AltModifier)
        dialog.composer.insertPlainText('第二行')
        self.assertFalse(actions)
        self.assertTrue(dialog.send_button.isEnabled())
        QTest.keyClick(dialog.composer, Qt.Key.Key_Return)
        QTest.keyClick(dialog.composer, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(actions, [('ai_chat_send', ('fixture', '第一行\n第二行'))] * 2)
        dialog.close()

    def test_live_logs_apply_batches_at_capacity_without_rebuilding_document(self):
        panel = self.window.logs
        panel.clear_display()
        panel.set_export_enabled(True)
        panel.set_scope('project-a', '合成项目', 'job-a', (7,))
        panel.scope.setCurrentIndex(panel.scope.findData(7))
        initial = tuple(
            LogView('09:10:11', 'INFO', 'project-a', '合成项目', f'批量记录 {number:04d}', 'job-a', 7)
            for number in range(panel.MAX_LINES)
        )
        panel.append_batch(initial)
        scroll = panel.text.verticalScrollBar()
        panel.auto_scroll.setChecked(False)
        scroll.setValue(scroll.maximum() // 2)
        previous_position = scroll.value()
        self.assertGreater(previous_position, 0)
        self.assertEqual(panel.text.document().blockCount(), panel.MAX_LINES)
        hidden = LogView('09:10:12', 'INFO', 'project-b', '其它项目', '不可见', 'job-a', 7)
        multiline = LogView('09:10:12', 'ERROR', 'project-a', '合成项目',
                            '新异常 😀\r\n第二行', 'job-a', 7)
        tail = LogView('09:10:12', 'INFO', 'project-a', '合成项目', '最新通道记录', 'job-a', 7)

        with patch.object(panel.text, 'setPlainText', wraps=panel.text.setPlainText) as rebuild:
            panel.append_batch((hidden, multiline, tail))
            rebuild.assert_not_called()
        visible = panel.text.toPlainText()
        self.assertEqual(scroll.value(), previous_position)
        self.assertEqual(visible.count('\n') + 1, panel.MAX_LINES - 1)
        self.assertIn('批量记录 0004', visible.split('\n', 1)[0])
        self.assertIn('新异常 😀\n第二行', visible)
        self.assertTrue(visible.endswith('最新通道记录'))
        self.assertNotIn('不可见', visible)

        exports = []
        panel.export_requested.connect(lambda entries, _description: exports.append(entries))
        panel.request_export()
        self.assertEqual(exports, [initial[4:] + (multiline, tail)])
        with patch.object(panel.text, 'setPlainText', wraps=panel.text.setPlainText) as rebuild:
            for batch in range(32):
                rows = tuple(LogView('09:10:13', 'INFO', 'project-a', '合成项目',
                    f'持续批次 {batch:02d}/{number:02d}', 'job-a', 7) for number in range(20))
                panel.append_batch(rows)
            rebuild.assert_not_called()
        self.assertEqual(panel.text.document().blockCount(), panel.MAX_LINES - 1)
        self.assertIn('批量记录 0644', panel.text.toPlainText().split('\n', 1)[0])
        self.assertTrue(panel.text.toPlainText().endswith('持续批次 31/19'))
        self.assertEqual(scroll.value(), previous_position)
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            self.assertTrue(self.window.grab().save(str(Path(output) / 'live-log-batch-at-capacity.png')))
        panel.level.setCurrentText('ERROR')
        self.assertTrue(panel.text.toPlainText().endswith('新异常 😀\n第二行'))
        panel.auto_scroll.setChecked(True)
        next_error = LogView('09:10:13', 'ERROR', 'project-a', '合成项目', '后续异常', 'job-a', 7)
        panel.append_batch((next_error,))
        self.assertTrue(panel.text.toPlainText().endswith('后续异常'))
        self.assertEqual(scroll.value(), scroll.maximum())
        self.assertEqual(exports[0][-1], tail)
        panel.clear_display()
        self.assertFalse(panel.export_button.isEnabled())
        self.assertEqual(panel.text.toPlainText(), '')

    def test_global_log_filter_pins_project_identity_across_navigation_and_close(self):
        from dataclasses import replace

        first, second = (replace(project, name='同名') for project in self.window.projects[:2])
        self.window.set_projects((first, second))
        panel = self.window.logs
        panel.clear_display()
        panel.set_export_enabled(True)
        rows = (
            LogView('10:00', 'INFO', '', '工作区', '全局记录'),
            LogView('10:01', 'ERROR', first.project_id, '同名', '超时 A'),
            LogView('10:02', 'ERROR', second.project_id, '同名', '超时 B'),
            LogView('10:03', 'INFO', first.project_id, '同名', '已恢复 A'),
            LogView('10:04', 'WARN', 'closed-id', '旧项目', '旧缓冲'),
        )
        panel.append_batch(rows)
        combo = panel.project_filter
        combo.showPopup()
        self.app.processEvents()
        combo.hidePopup()
        self.assertGreater(combo.findData('closed-id'), 0)
        self.assertIn(first.project_id, combo.itemText(combo.findData(first.project_id)))
        combo.setCurrentIndex(combo.findData(''))
        self.assertEqual(tuple(panel._selected), (rows[0],))
        combo.setCurrentIndex(combo.findData(first.project_id))
        panel.level.setCurrentText('ERROR')
        panel.search.setText('超时')
        self.assertEqual(tuple(panel._selected), (rows[1],))
        exports = []
        panel.export_requested.connect(lambda entries, description: exports.append((entries, description)))
        panel.request_export()
        self.window.select_project(second.project_id)
        self.assertFalse(combo.isVisible())
        self.assertEqual(tuple(panel._selected), (rows[2],))
        self.window.show_dashboard()
        self.assertTrue(combo.isVisible())
        self.window.set_projects((second,))
        self.assertEqual(tuple(panel._selected), (rows[1],))
        panel.clear_display()
        self.assertEqual(combo.currentData(), first.project_id)
        with patch.object(panel.text, 'setPlainText', wraps=panel.text.setPlainText) as rebuild:
            panel.append_batch((rows[2], rows[1]))
            rebuild.assert_not_called()
        self.assertEqual(tuple(panel._selected), (rows[1],))
        self.assertEqual(exports[0][0], (rows[1],))
        self.assertIn(first.project_id, exports[0][1])

    def test_overview_metrics_and_filter_follow_project_identity_and_latest_evidence(self):
        from dataclasses import replace

        base = self.window.projects[0]
        busy = replace(base, project_id='a', active_task_count=3, attention_count=2,
                       success_count=7, failure_count=2)
        waiting = replace(base, project_id='b', state='queued', state_text='等待资源',
                          active_task_count=0, observed_active_task_count=2)
        done = replace(base, project_id='c', state='idle', state_text='空闲',
                       overview_state='completed', active_task_count=0)
        uncertain = replace(base, project_id='d', state='unknown', state_text='待核实',
                            unresolved_tasks=True, active_task_count=0,
                            success_count=None, failure_count=None)
        self.window.set_projects((replace(busy, state='completed'), waiting, done, uncertain, busy))
        board = self.window.dashboard
        self.assertEqual(self.window.navigation_model.item(0).rowCount(), 2)
        self.assertEqual([label.text() for label in board.metric_numbers], ['4', '1', '1', '1', '2', '1'])
        for key, expected in (('running', {'a'}), ('queued', {'b'}), ('completed', {'c'}),
                              ('attention', {'a', 'd'}), ('unknown', {'d'}), ('active', {'a', 'b'})):
            board.state_filter.setCurrentIndex(board.state_filter.findData(key))
            for view in (board.table, board.cards):
                model = view.model()
                self.assertEqual({model.index(row, 0).data(Qt.UserRole).project_id
                                  for row in range(model.rowCount())}, expected)
        for row, expected in ((0, ('7', '2')), (3, ('—', '—'))):
            self.assertEqual(tuple(board.model.index(row, col).data() for col in (6, 7)), expected)
        board.clear_project_filter()
        for width in (1480, 850):
            self.window.resize(width, 750)
            self.app.processEvents()
            for card in board.metric_cards:
                self.assertTrue(card.isVisible())
                self.assertTrue(board.rect().contains(card.geometry()))
                self.assertGreaterEqual(card.width(), card.minimumSizeHint().width())
            for idx, card in enumerate(board.metric_cards):
                self.assertTrue(all(not card.geometry().intersects(other.geometry())
                                    for other in board.metric_cards[idx + 1:]))

    def test_demo_metrics_keep_task_and_health_distinct(self):
        self.assertEqual([w.text() for w in self.window.dashboard.metric_numbers], ['5', '3', '1', '0', '1', '0'])
        aging = self.window.projects[-1]
        self.assertEqual(aging.state, 'pending')
        self.assertIsNone(aging.progress)
        self.assertFalse(aging.channels)
        self.assertIn('演示', self.window.mode_label.text())
        self.assertFalse(self.window.detail.start_button.isEnabled())
        self.assertFalse(self.window.detail.stop_button.isEnabled())

    def test_project_status_is_consistent_across_navigation_cards_table_and_detail(self):
        from dataclasses import replace
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QColor, QIcon
        from src.services.power_worker_lifetime import UNVERIFIED
        from src.ui.qt.showcase_components import project_status_style
        from src.ui.qt.theme import V13_PALETTE

        dashboard = self.window.dashboard
        base = replace(projects()[0], name='样机验证项目', channels=(), channel_text='已选 1 通道',
                       progress=None, progress_text='等待原业务进度事件', success_count=None, failure_count=None)
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        cases = (
            ('failed', '部分失败', V13_PALETTE.error),
            ('unchecked', '完成（含未校验）', V13_PALETTE.warning),
            ('unknown', '历史任务待核实', V13_PALETTE.neutral),
            ('recovery_required', '需要恢复确认', V13_PALETTE.warning),
            ('completed', '已确认手动重启', V13_PALETTE.success),
            ('running', '运行中 !', V13_PALETTE.success),
            ('queued', '等待执行', None),
            ('stopping', '停止中', None),
            ('stopped', '未执行', None),
            ('idle', '空闲', None),
            ('pending', '待接入', None),
            ('future-state', '来自旧项目的状态', V13_PALETTE.neutral),
        )
        for state, caption, palette in cases:
            with self.subTest(state=state):
                row = replace(base, state=state, state_text=caption, active_task_count=int(state == 'running'),
                              test_type={'failed': '全流程测试', 'unchecked': '挂测前预测试'}.get(state, base.test_type),
                              progress_text=caption, attention_count=int(state in ('failed', 'unknown')))
                self.window.set_projects((row,))
                self.window.show_dashboard()
                self.app.processEvents()
                group = self.window.navigation_model.item(0 if row.active_task_count else 1)
                item = group.child(0)
                self.assertEqual(item.data(Qt.ItemDataRole.UserRole), row.project_id)
                self.assertIn(caption, item.toolTip())
                idx = dashboard.proxy.index(0, 2)
                self.assertEqual(idx.data(), caption)
                table_icon = idx.data(Qt.ItemDataRole.DecorationRole)
                self.assertFalse(table_icon.isNull())
                self.assertEqual(item.icon().cacheKey(), table_icon.cacheKey())
                style = project_status_style(state)
                if palette is not None:
                    self.assertEqual(style.color, palette.symbol)
                if state == 'failed':
                    for mode in (QIcon.Mode.Normal, QIcon.Mode.Selected):
                        symbol = table_icon.pixmap(QSize(48, 48), mode, QIcon.State.On).toImage()
                        colors = {symbol.pixel(x, y) for y in range(symbol.height()) for x in range(symbol.width())}
                        self.assertIn(QColor(style.ink).rgb(), colors)
                        self.assertIn(QColor(style.background).rgb(), colors)
                card_rect = dashboard.cards.visualRect(dashboard.proxy.index(0, 0))
                self.assertTrue(card_rect.isValid())
                card_rect.setHeight(52)
                header = dashboard.cards.viewport().grab(card_rect).toImage()
                sampled = {header.pixel(x, y) for x in range(0, header.width(), 2)
                           for y in range(0, header.height(), 2)}
                self.assertIn(QColor(style.background).rgb(), sampled)
                if output and state == 'failed':
                    self.assertTrue(self.window.grab().save(str(Path(output) / 'project-status-overview.png')))
                self.window.select_project(row.project_id)
                self.assertEqual(self.window.detail.state.text(), caption)
                self.assertEqual(self.window.detail.state.accessibleName(), caption)
                if output and state == 'unchecked':
                    self.app.processEvents()
                    self.assertTrue(self.window.grab().save(str(Path(output) / 'project-status-unchecked.png')))
        self.window.resize(900, 720)
        self.window.set_projects((replace(base, state='unknown', state_text=UNVERIFIED),))
        self.app.processEvents()
        badge = self.window.detail.state
        self.assertEqual(badge.text(), UNVERIFIED)
        self.assertEqual(badge.toolTip(), UNVERIFIED)
        self.assertEqual(badge.accessibleName(), UNVERIFIED)
        self.assertTrue(self.window.detail.rect().contains(badge.mapTo(self.window.detail, badge.rect().bottomRight())))

    def test_channel_matrix_and_list_share_the_same_snapshots(self):
        from dataclasses import replace
        from PySide6.QtWidgets import QStyle, QStyleOptionButton
        from src.ui.qt.showcase_components import STATUS_STYLES
        from src.ui.qt.theme import V13_PALETTE

        self.window.select_project('demo-a')
        detail = self.window.detail
        before = self.window.projects
        QTest.mouseClick(detail.table_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(detail.channel_model.channels, detail.channels.channels)
        self.assertEqual(detail.channel_model.rowCount(), 3)
        self.assertEqual([detail.channel_model.index(i, 0).data(Qt.ItemDataRole.UserRole)
                          for i in range(3)], [1, 2, 7])
        self.assertEqual(self.window.projects, before)
        self.assertFalse(detail.channel_edit_button.isEnabled())
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        for width, height in ((1366, 768), (1000, 700)):
            self.window.resize(width, height)
            self.app.processEvents()
            self.assertEqual(detail.channel_table.horizontalScrollBar().maximum(), 0)
            self.assertLessEqual(detail.channel_table.width(), detail.execution_scroll.viewport().width())
            if output:
                self.assertTrue(self.window.grab().save(str(Path(output) / f'channel-list-{width}.png')))
        QTest.mouseClick(detail.matrix_button, Qt.MouseButton.LeftButton)
        self.assertEqual(detail.channel_modes.currentIndex(), 0)

        project = before[0]
        long_vlan = 'VLAN-设备环境-' + '设备通道' * 12
        idle_channels = tuple(replace(channel, state='unknown', cycle=None, selected=True)
                              for channel in project.channels[:8])
        idle = replace(project, channels=(idle_channels[0],
            replace(idle_channels[1], port=''), replace(idle_channels[2], vlan=''),
            replace(idle_channels[3], vlan='', port=''), replace(idle_channels[4], vlan=long_vlan),
            *idle_channels[5:], *project.channels[8:]))
        self.window.resize(1480, 900)
        self.window.set_projects((idle, *before[1:]))
        QTest.qWait(30)
        self.assertTrue(detail.channels.isVisible())

        def tile_colors(tile):
            pixmap = tile.grab()
            image = pixmap.toImage()
            left = round(pixmap.devicePixelRatio())
            center = image.height() // 2
            return (image.pixelColor(image.width() - 7, center).name(),
                    image.pixelColor(left, center).name())

        self.assertEqual(detail.channels.channels, idle.channels[:8])
        self.assertEqual(detail.channel_model.channels, idle.channels[:8])
        self.assertEqual(len(detail.channels.tiles), 8)
        for index, tile in enumerate(detail.channels.tiles):
            channel = idle.channels[index]
            self.assertTrue(tile.isVisible())
            self.assertEqual(tile.text().splitlines()[:2], [f'CH{channel.number:02d}  未知', '已选'])
            self.assertEqual(tile_colors(tile), (V13_PALETTE.selected_background.lower(), V13_PALETTE.brand.lower()))
            self.assertEqual(detail.channel_model.index(index, 3).data(), channel.vlan or '未配置')
            self.assertEqual(detail.channel_model.index(index, 4).data(), channel.port or '未配置')
            binding_lines = tile.text().splitlines()[2:]
            if channel.vlan == long_vlan:
                self.assertEqual(len(binding_lines), 1)
                self.assertTrue(binding_lines[0].startswith('VLAN-'))
                self.assertTrue(binding_lines[0].endswith('… / COM20'))
                self.assertIn(long_vlan + ' / COM20', tile.toolTip())
            else:
                binding = ' / '.join(filter(None, (channel.vlan, channel.port)))
                self.assertEqual(binding_lines, [binding] if binding else [])

        for width, height in ((1366, 768), (800, 440), (1480, 900)):
            self.window.resize(width, height)
            QTest.qWait(30)
            self.assertEqual(detail.execution_scroll.horizontalScrollBar().maximum(), 0)
            for tile in detail.channels.tiles:
                self.assertTrue(detail.channels.rect().contains(tile.geometry()), (detail.channels.rect(), tile.geometry()))
                option = QStyleOptionButton()
                tile.initStyleOption(option)
                content = tile.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, tile)
                lines = tile.text().splitlines()
                metrics = tile.fontMetrics()
                text_width = max(metrics.horizontalAdvance(line) for line in lines)
                text_height = metrics.height() + (len(lines) - 1) * metrics.lineSpacing()
                self.assertGreaterEqual(content.width(), text_width + tile.iconSize().width() + 4,
                                        (tile.text(), tile.size(), content, text_width))
                self.assertGreaterEqual(content.height(), text_height)

        first, second = detail.channels.tiles[:2]
        first.setFocus(Qt.FocusReason.TabFocusReason)
        QTest.keyClick(first, Qt.Key.Key_Tab)
        self.assertTrue(second.hasFocus())
        focused = second.grab().toImage()
        self.assertEqual(focused.pixelColor(focused.width() // 2, 0).name(), V13_PALETTE.info.lower())
        self.assertEqual(tile_colors(second)[1], V13_PALETTE.brand.lower())
        QTest.mouseClick(first, Qt.MouseButton.LeftButton)
        dialog = detail.dialogs[-1]
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.windowTitle(), 'CH01 · 通道快照')
        dialog.close()

        for state, style, caption in (('running', 'running', '运行中'), ('success', 'healthy', '正常'),
                                     ('failed', 'error', '异常'), ('retry', 'warning', '重试中')):
            updated = replace(idle, channels=(replace(idle.channels[0], state=state, cycle=4, stage='检测线路'),
                                             *idle.channels[1:]))
            self.window.set_projects((updated, *before[1:]))
            self.app.processEvents()
            tile = detail.channels.tiles[0]
            self.assertTrue(tile.isVisible())
            self.assertEqual(tile.text().splitlines(),
                             [f'CH01  {caption}', '已选', '已完成 4 轮 · 检测线路', 'VLAN116 / COM16'])
            self.assertEqual(tile_colors(tile), (STATUS_STYLES[style].background.lower(), V13_PALETTE.brand.lower()))

        empty = replace(idle, channels=tuple(replace(channel, selected=False) for channel in idle.channels))
        self.window.set_projects((empty, *before[1:]))
        self.assertEqual(detail.channels.tiles, [])
        self.assertEqual(detail.channel_model.rowCount(), 0)
        self.assertTrue(detail.no_channels.isVisible())
        self.assertFalse(detail.channel_modes.isVisible())
        self.window.set_projects(before)
        self.assertEqual(len(detail.channels.tiles), 3)
        self.assertTrue(detail.channel_modes.isVisible())
        self.assertFalse(detail.no_channels.isVisible())

    def test_live_refresh_preserves_navigation_selection_and_config_controls(self):
        from dataclasses import replace
        from PySide6.QtCore import QPersistentModelIndex
        self.window.select_project('demo-a')
        first_control = self.window.detail.config_layout.itemAt(0).widget()
        model_index = QPersistentModelIndex(self.window.dashboard.model.index(0, 0))
        group = self.window.navigation_model.index(1, 0)
        self.window.navigation.setExpanded(group, False)
        updated = tuple(replace(p, elapsed='02:36:19') if p.project_id == 'demo-a' else p for p in self.window.projects)
        self.window.set_projects(updated)
        self.app.processEvents()
        self.assertTrue(model_index.isValid())
        self.assertEqual(self.window.selected_project, 'demo-a')
        self.assertEqual(self.window.navigation.currentIndex().data(Qt.ItemDataRole.UserRole), 'demo-a')
        self.assertFalse(self.window.navigation.isExpanded(self.window.navigation_model.index(1, 0)))
        self.assertIs(self.window.detail.config_layout.itemAt(0).widget(), first_control)
        from PySide6.QtWidgets import QLabel
        detail = self.window.detail
        for source, title in [('本次任务配置快照', '任务配置快照'), ('', '测试配置')]:
            updated = tuple(replace(p, channel_snapshot_label=source) if p.project_id == 'demo-a' else p
                            for p in updated)
            self.window.set_projects(updated)
            row = detail.config_layout.itemAt(0).widget()
            self.assertIn(title, [item.text() for item in row.findChildren(QLabel)])
        for width in (900, 1480):
            self.window.resize(width, 768)
            QTest.qWait(30)
            self.assertEqual(detail.width() < 850, width == 900)
            capture = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if capture and width == 900:
                self.assertTrue(self.window.grab().save(str(Path(capture) / 'compact-project-controls.png')))
            for control in (detail.pipeline_button, detail.environment_button, detail.start_button, detail.stop_button):
                self.assertTrue(control.isVisibleTo(self.window))
                self.assertTrue(detail.rect().contains(control.mapTo(detail, control.rect().topLeft())))
                self.assertTrue(detail.rect().contains(control.mapTo(detail, control.rect().bottomRight())))

    def test_cards_table_search_and_navigation_share_identity(self):
        dashboard = self.window.dashboard
        dashboard.set_mode(1)
        dashboard.search.setText('上下电')
        self.assertEqual(dashboard.proxy.rowCount(), 2)
        dashboard.state_filter.setCurrentIndex(dashboard.state_filter.findData('attention'))
        self.assertEqual(dashboard.proxy.rowCount(), 0)
        dashboard.search.clear()
        self.assertEqual(dashboard.proxy.rowCount(), 1)
        index = dashboard.proxy.index(0, 0)
        dashboard._selected(index)
        self.assertEqual(self.window.selected_project, 'demo-c')
        self.assertIs(self.window.pages.currentWidget(), self.window.detail)
        self.window.show_dashboard()
        self.assertEqual(self.window.dashboard.model.rowCount(), 5)

    def test_single_card_uses_available_width_and_logs_are_draggable(self):
        self.window.set_projects(projects()[:1])
        self.app.processEvents()
        view = self.window.dashboard.cards
        self.assertGreaterEqual(view.gridSize().width(), view.viewport().width() - 2)
        self.assertGreaterEqual(view.visualRect(view.model().index(0, 0)).width(), view.viewport().width() * .9)
        handle = self.window.vertical.handle(1)
        old = self.window.vertical.sizes()[1]
        start = handle.rect().center()
        target = start + QPoint(0, -70)
        QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(handle, target, delay=20)
        QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=target)
        QTest.qWait(20)
        self.assertGreater(self.window.vertical.sizes()[1], old + 20)
        self.window.logs.toggle_expanded()
        self.app.processEvents()
        self.assertFalse(self.window.logs.text.isVisible())
        self.window.logs.toggle_expanded()
        self.app.processEvents()
        self.assertTrue(self.window.logs.text.isVisible())

    def test_project_switch_keeps_snapshots_and_filters_logs(self):
        original = self.window.projects
        for _ in range(8):
            self.window.select_project('demo-a')
            self.window.select_project('demo-b')
            self.window.show_dashboard()
        self.assertIs(self.window.projects, original)
        self.window.select_project('demo-a')
        text = self.window.logs.text.toPlainText()
        self.assertIn('第68轮', text)
        self.assertNotIn('校验超时', text)
        self.assertEqual([channel.number for channel in self.window.detail.channels.channels], [1, 2, 7])
        self.window.detail.open_channel(1)
        self.app.processEvents()
        self.assertTrue(self.window.detail.dialogs[-1].isVisible())

    def test_log_buffer_is_bounded_and_event_loop_stays_responsive(self):
        entries = [LogView('00:00:00', 'INFO', 'demo-a', '演示', 'payload-' + str(n)) for n in range(12000)]
        self.window.logs.append_batch(entries)
        self.assertLessEqual(len(self.window.logs.entries), 5000)
        self.assertLessEqual(self.window.logs.text.document().blockCount(), 5000)
        self.assertIn('payload-11999', self.window.logs.text.toPlainText())
        ticks = []
        timer = QTimer(self.window)
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(10)
        QTest.qWait(80)
        timer.stop()
        self.assertGreaterEqual(len(ticks), 2)
        self.window.logs.clear_display()
        self.assertEqual(self.window.logs.text.toPlainText(), '')

    def test_background_thread_cannot_update_presentation(self):
        errors = []
        def worker():
            try:
                self.window.set_projects(())
            except RuntimeError as error:
                errors.append(str(error))
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(self.window.projects), 5)

    def test_responsive_layout_and_native_captures(self):
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        directory = Path(output) if output else None
        if directory:
            directory.mkdir(parents=True, exist_ok=True)
        scale = self.window.devicePixelRatioF()
        results = []
        for width, height in ((1920, 1080), (1366, 768)):
            requested = (round(width / scale), round(height / scale))
            self.window.resize(*requested)
            self.window.show_dashboard()
            QTest.qWait(40)
            self.assertLessEqual(self.window.width(), requested[0] + 2)
            self.assertLessEqual(self.window.height(), requested[1] + 2)
            self.assertEqual(self.window.dashboard.cards.horizontalScrollBar().maximum(), 0)
            self.assertTrue(self.window.logs.fold_button.isVisible())
            suffix = f'{width}x{height}-{scale:g}'
            if directory:
                self.assertTrue(self.window.grab().save(str(directory / f'overview-{suffix}.png')))
            cards = self.window.dashboard.cards
            rectangles = [[cards.visualRect(cards.model().index(n, 0)).x(),
                           cards.visualRect(cards.model().index(n, 0)).y(),
                           cards.visualRect(cards.model().index(n, 0)).width()]
                          for n in range(cards.model().rowCount())]
            if width == 1920 and scale == 1:
                self.assertEqual([r[1] for r in rectangles[:4]], [0, 0, 0, 0])
            self.window.select_project('demo-a')
            QTest.qWait(40)
            detail = self.window.detail
            self.assertLessEqual(detail.execution.width(), detail.execution_scroll.viewport().width())
            self.assertTrue(detail.start_button.isVisible())
            self.assertTrue(detail.stop_button.isVisible())
            if directory:
                self.assertTrue(self.window.grab().save(str(directory / f'detail-{suffix}.png')))
            results.append(dict(physical_request=[width, height], logical_request=requested,
                actual_logical=[self.window.width(), self.window.height()], dpr=scale,
                card_rectangles=rectangles, card_viewport=[cards.viewport().width(), cards.viewport().height()],
                card_grid=[self.window.dashboard.cards.gridSize().width(), self.window.dashboard.cards.gridSize().height()]))
        self.window.select_project('demo-e')
        self.app.processEvents()
        self.assertFalse(self.window.detail.progress.isVisible())
        if directory:
            self.window.grab().save(str(directory / f'aging-pending-{scale:g}.png'))
            (directory / f'geometry-{scale:g}.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')


class QtProjectWorkspaceTests(unittest.TestCase):
    def setUp(self):
        from qt_execution_fakes import block_live_model_transport, install_native_fixture_locks
        block_live_model_transport(self)
        install_native_fixture_locks(self)
        self.scope = install_qt_test_scope(self)
        self.app = self.scope.app
        for target, empty in (('src.core.network_adapter.read_adapter_identities', ()),
                              ('src.core.serial_inventory.list_serial_port_names', [])):
            enumeration = patch(target, return_value=empty)
            enumeration.start()
            self.addCleanup(enumeration.stop)
        self.temporary = tempfile.TemporaryDirectory(prefix='qt-real-project-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.window = MainWindow(demo=False)
        apply_theme(self.scope.app)
        self.controller = WorkspaceController(self.window, Path(__file__).resolve().parents[1], directory=self.root / 'workspace')
        self.addCleanup(self.close_workspace)
        self.window.resize(1366, 768)
        self.window.show()
        self.wait_for(lambda: self.controller.ready)

    def test_feishu_sdk_repair_is_opt_in_and_requests_safe_close(self):
        from PySide6.QtWidgets import QMessageBox
        from unittest.mock import Mock
        from src.services.feishu_dependency_repair import FeishuDependencyRepair

        lease, installer = Mock(), Mock()

        def repair(root, gate):
            return FeishuDependencyRepair(root, gate, installer=installer, lease_factory=lambda _: lease)

        controller = self.controller.feishu_repair
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as confirm:
            controller.open()
        self.assertEqual(confirm.call_args.args[-1], QMessageBox.StandardButton.No)
        self.assertIsNone(controller.dialog)
        installer.assert_not_called()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
                patch('src.services.qt_feishu_repair.find_spec', return_value=None), \
                patch('src.services.qt_feishu_repair.FeishuDependencyRepair', side_effect=repair), \
                patch('src.services.feishu_dependency_repair.source_environment', return_value=self.root):
            controller.open()
            self.assertTrue(controller.dialog.isVisible())
            self.assertFalse(controller.dialog.close())
            self.wait_for(lambda: self.controller.adapter.closed.is_set())
        self.assertTrue(self.controller.closing)
        self.assertTrue(controller.restart_requested)
        installer.assert_called_once()
        lease.close.assert_called_once()

    def test_platform_credential_dialog_masks_secret_and_saves_only_after_confirmation(self):
        from PySide6.QtWidgets import QLineEdit, QMessageBox

        self.controller.submit('create', self.root / 'platform-project', '接入验证项目')
        self.wait_for(lambda: self.controller._current() is not None)
        self.controller.open_platform_configuration('feishu')
        dialog = self.controller.platform_configuration_dialog
        self.wait_for(lambda: dialog.view is not None)
        self.assertEqual(dialog.fields['app_secret'].echoMode(), QLineEdit.EchoMode.Password)
        dialog.fields['app_id'].setText('cli_fixture')
        dialog.fields['app_secret'].setText('fixture-secret')
        store = self.controller.adapter._service.platform_config('feishu')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            dialog.save_button.click()
        self.assertFalse(store.path.exists())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes) as confirm:
            dialog.save_button.click()
        self.assertEqual(confirm.call_args.args[-1], QMessageBox.StandardButton.No)
        self.wait_for(lambda: dialog.feedback.text().startswith('已保存。'))
        self.assertEqual(dialog.fields['app_secret'].text(), '')
        self.assertFalse(store.load()['enabled'])
        self.assertTrue(dialog.close())

    def test_qt_controlled_extension_preview_starts_unchecked_and_approves_only_reviewed_hash(self):
        from PySide6.QtWidgets import QFileDialog

        self.controller.submit('create', self.root / 'extension-project', '审阅项目')
        self.wait_for(lambda: self.controller._current() is not None)
        self.controller.open_extensions()
        dialog = self.controller.extensions_dialog
        self.wait_for(dialog.import_button.isEnabled)
        path = self.root / 'review.json'
        fixture = dict(id='local_fixture', name='查询通道', version='1', description='模拟审阅',
                       target_capability='channels.list', input_schema=dict(type='object', additionalProperties=False),
                       arguments={}, bindings={}, allowed_channels=[1])
        path.write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(path), 'JSON')):
            dialog.import_button.click()
        self.wait_for(lambda: dialog.review is not None)
        self.assertFalse(dialog.review.accepted_review.isChecked())
        self.assertFalse(dialog.review.approve.isEnabled())
        dialog.review.accepted_review.setChecked(True)
        dialog.review.approve.click()
        self.wait_for(lambda: dialog.rows.count() == 1)
        self.assertIn('local_fixture', dialog.rows.item(0).text())
        self.assertTrue(dialog.close())

    def test_qt_feishu_automatic_notifications_require_local_confirmation(self):
        from PySide6.QtWidgets import QMessageBox

        self.controller.submit('create', self.root / 'notification-project', '通知项目')
        self.wait_for(lambda: self.controller._current() is not None)
        project = self.controller._current()
        service = self.controller.adapter._service
        context = service.projects.opened[project.project_id]
        (context.config_dir / 'test_project_config.ini').write_text(
            '[project_info]\nproject_name=通知项目\n', encoding='utf-8')
        original_revision = context.saved_root
        self.controller.submit('save', project.project_id)
        self.wait_for(lambda: context.saved_root != original_revision)
        store = service.platform_config('feishu')
        store.save(dict(store.defaults(), app_id='cli_fixture', app_secret='fixture-secret',
                        group='confirmed-group', corp='tenant', group_name='群'))
        self.controller.open_platform_configuration('feishu')
        dialog = self.controller.platform_configuration_dialog
        self.wait_for(dialog.notify_action.isEnabled)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            dialog.notify_action.trigger()
        self.assertFalse(store.load()['push_enabled'])
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes) as confirm:
            dialog.notify_action.trigger()
        self.assertIn('confirmed-group', confirm.call_args.args[2])
        self.wait_for(lambda: dialog.view['notifications_enabled'])
        self.assertTrue(store.load()['push_enabled'])
        self.assertFalse(store.load()['enabled'])
        self.assertTrue(dialog.close())

    def test_qt_history_requests_safe_stop_only_after_local_confirmation(self):
        from PySide6.QtWidgets import QMessageBox
        from src.models.qt_log_history import HistoryJob, HistoryPage
        from src.ui.qt.log_history_dialog import LogHistoryDialog

        self.controller.submit('create', self.root / 'job-project', '任务项目')
        self.wait_for(lambda: self.controller._current() is not None)
        dialog = LogHistoryDialog(self.controller._current(), self.window)
        dialog.show()
        dialog.show_jobs(HistoryPage((HistoryJob('active-fixture', 'aging.start', 'running', 'now'),), None))
        receipts = []
        dialog.stop_requested.connect(receipts.append)
        self.assertTrue(dialog.stop_action.isEnabled())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as confirm:
            dialog.stop_action.trigger()
        self.assertEqual(confirm.call_args.args[-1], QMessageBox.StandardButton.No)
        self.assertFalse(receipts)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            dialog.stop_action.trigger()
        self.assertEqual(receipts, ['active-fixture'])
        dialog.show_review_state('active-fixture', 'stop_requested')
        dialog.set_busy(False)
        self.assertFalse(dialog.stop_action.isEnabled())
        self.assertTrue(dialog.close())

    def wait_for(self, predicate):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            self.scope.app.processEvents()
            if predicate():
                return
            # QTest.qWait holds the binding's GIL on this PySide version;
            # QApplication.exec normally releases it. Yield explicitly while
            # this test pumps events so the real file worker can make progress.
            time.sleep(.01)
        self.fail('Qt project result did not arrive: ' + self.window.statusBar().currentMessage() +
                  ' / ' + self.window.mode_label.text())

    def close_workspace(self):
        from PySide6.QtWidgets import QMessageBox
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            for dialog in tuple(self.controller.configuration_editors.values()):
                dialog.close()
            for dialog in tuple(self.controller.ai_chat.case_windows.values()):
                dialog.close()
        self.controller.timer.stop()
        self.window._close_coordinator = None
        if not self.controller.adapter.closed.is_set():
            self.controller.adapter.begin_close({p.project_id: 'discard' for p in self.window.projects})
        self.assertTrue(self.controller.adapter.wait_closed(5))
        self.window.close()

    def test_qt_navigation_opens_saved_template_sources_and_cached_devices(self):
        from dataclasses import replace
        from src.services.qt_host_inventory import HostInventoryReading

        window, controller = self.window, self.controller
        self.assertEqual(window.navigation_model.item(0).text(), '活动项目（0）')
        self.assertIn('0 个项目', window.project_status.text())
        window.templates_button.click()
        self.assertTrue(window.templates_page.empty.isVisible())
        names = ('source-a', 'source-b')
        for count, folder in enumerate(names, 1):
            controller.submit('create', self.root / folder, '同名配置来源')
            self.wait_for(lambda: len(window.projects) == count and bool(window.selected_project))
        before = {folder: (self.root / folder / 'project.linecheck.json').read_bytes() for folder in names}
        self.assertIn(controller.duplicate_action, window.project_management_button.menu().actions())
        self.assertIs(window.sidebar_settings_button.menu(), window.settings_button.menu())
        self.assertIn(controller.history_action, window.history_button.menu().actions())
        self.assertIn(controller.archived_logs_action, window.history_button.menu().actions())

        window.sidebar_search.setText('未匹配的名字')
        window.templates_button.click()
        page = window.templates_page
        self.assertIs(window.pages.currentWidget(), page)
        self.assertEqual(window.selected_project, '')
        self.assertEqual(page.model.rowCount(), 2)
        self.assertEqual(page.model.index(0, 0).data(), page.model.index(1, 0).data())
        first, second = (page.model.index(i, 0).data(Qt.ItemDataRole.UserRole) for i in range(2))
        self.assertNotEqual(first, second)
        expected = next(project for project in window.projects if project.project_id == first)
        self.assertTrue(expected.saved_revision)
        self.assertEqual(page.model.index(0, 1).data(Qt.ItemDataRole.ToolTipRole), expected.saved_revision)
        directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if directory:
            self.assertTrue(window.grab().save(str(Path(directory) / 'saved-project-template-index.png')))
        original = window.projects
        last = replace(expected, dirty=True)
        window.set_projects((*original, last))
        self.assertEqual(len(window.projects), 2)
        self.assertEqual(page.model.rowCount(), 2)
        self.assertEqual(page.model.index(0, 2).data(), '有未保存更改')
        self.assertEqual(window.navigation_model.item(1).rowCount(), 2)
        window.set_projects(original)
        page.table.setCurrentIndex(page.model.index(0, 1))
        QTest.keyClick(page.table, Qt.Key.Key_Return)
        self.assertEqual(window.selected_project, first)
        self.assertIs(window.pages.currentWidget(), window.detail)
        self.assertEqual({folder: (self.root / folder / 'project.linecheck.json').read_bytes() for folder in names},
                         before)
        window.sidebar_search.clear()
        group = window.navigation_model.index(0, 0)
        QTest.mouseClick(window.navigation.viewport(), Qt.MouseButton.LeftButton,
                         pos=window.navigation.visualRect(group).center())
        self.assertIs(window.pages.currentWidget(), window.dashboard)
        self.assertEqual(window.dashboard.proxy.rowCount(), 0)
        window.overview_button.click()
        self.assertEqual(window.dashboard.proxy.rowCount(), 2)
        window.toggle_sidebar()
        self.assertFalse(window.sidebar.isVisible())
        window.toggle_sidebar()
        self.assertTrue(window.sidebar_devices_button.isVisible())

        reading = HostInventoryReading(('COM171',), ())
        with patch('src.services.qt_workspace_adapter.read_host_inventory', return_value=reading) as read:
            window.sidebar_devices_button.click()
            dialog = controller.device_inventory_dialog
            self.assertIsNotNone(dialog)
            self.assertIsNone(controller._inventory_request)
            read.assert_not_called()
            dialog.refresh_button.click()
            self.wait_for(lambda: dialog.ports.rowCount() == 1 and dialog.refresh_button.isEnabled())
            dialog.close()
            window.sidebar_devices_button.click()
            self.assertEqual(controller.device_inventory_dialog.ports.item(0, 0).text(), 'COM171')
            self.assertEqual(read.call_count, 1)
            controller.device_inventory_dialog.close()

    def test_qt_device_management_shows_readonly_inventory_and_active_workspace_leases(self):
        from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
        from src.models.network_adapter import AdapterIdentity
        from src.services.qt_host_inventory import HostInventoryReading

        identities = (AdapterIdentity('VLAN171', '{6bcb3b12-76f5-4074-a56e-32e120e539af}', 'Up'),
                      AdapterIdentity('实验室网卡', '{23bbf243-b27e-4e15-bd02-af44ae00ade7}', 'Down'))
        readings = (HostInventoryReading(('COM171', 'COM172'), identities), HostInventoryReading((), None))
        with patch('src.services.qt_workspace_adapter.read_host_inventory', side_effect=readings) as read:
            self.assertTrue(self.window.devices_action.isEnabled())
            self.window.devices_action.trigger()
            dialog = self.controller.device_inventory_dialog
            self.assertIsNotNone(dialog)
            self.wait_for(lambda: dialog.adapters.rowCount() == 2 and dialog.refresh_button.isEnabled())
            self.assertEqual(dialog.adapters.item(0, 2).text(), identities[0].interface_guid)
            self.assertEqual(dialog.ports.item(1, 0).text(), 'COM172')
            self.window.devices_action.trigger()
            self.assertIs(self.controller.device_inventory_dialog, dialog)
            self.assertEqual(read.call_count, 1)

            self.controller.submit('create', self.root / 'inventory-project', '模拟开关机项目')
            self.wait_for(lambda: len(self.window.projects) == 1)
            project = self.window.projects[0]
            workspace = self.controller.adapter._service
            context = workspace.projects.opened[project.project_id]
            config = ChannelConfigStore(context.config_dir / 'network_card_ip.ini')
            config.save([ChannelConfig('channel_7', vlan_name='VLAN171', serial_port='COM171', enabled=True)])
            self.controller.submit('refresh', project.project_id)
            self.wait_for(lambda: dialog.bindings.rowCount() == 1)
            self.assertEqual([dialog.bindings.item(0, i).text() for i in range(5)],
                             ['模拟开关机项目', 'CH07', '已选', 'VLAN171', 'COM171'])

            resources = workspace.resources
            owner = 'native-inventory-fixture'
            resources.acquire(owner, project.project_id, project.name, ('adapter:VLAN171', 'power:COM171'))
            try:
                self.wait_for(lambda: dialog.adapters.item(0, 3).text() == project.name)
                self.assertEqual(dialog.ports.item(0, 1).text(), project.name)
                self.assertEqual(dialog.adapters.item(1, 3).text(), '—')
                output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
                if output:
                    self.assertTrue(dialog.grab().save(str(Path(output) / 'device-inventory.png')))
                dialog.refresh_button.click()
                self.wait_for(lambda: '读取失败' in dialog.adapter_status.text() and dialog.refresh_button.isEnabled())
                self.assertEqual(dialog.adapters.rowCount(), 2)
                self.assertEqual(dialog.ports.rowCount(), 0)
                self.assertEqual(read.call_count, 2)
            finally:
                resources.release(owner)
            self.wait_for(lambda: dialog.adapters.item(0, 3).text() == '—')
            dialog.close()
            self.assertIsNone(self.controller.device_inventory_dialog)
            self.window.devices_action.trigger()
            self.assertEqual(self.controller.device_inventory_dialog.adapters.rowCount(), 2)
            self.assertEqual(read.call_count, 2)
            self.controller.device_inventory_dialog.close()

    def test_qt_device_resource_details_follow_real_leases_and_unresolved_protection(self):
        from PySide6.QtWidgets import QAbstractItemView

        controller = self.controller
        manager = controller.adapter._service.resources
        for suffix in ('a', 'b'):
            controller.submit('create', self.root / ('lease-project-' + suffix), '同名项目')
        self.wait_for(lambda: len(self.window.projects) == 2)
        a, b = self.window.projects
        with patch('src.services.qt_workspace_adapter.read_host_inventory') as read:
            self.window.sidebar_devices_button.click()
            dialog = controller.device_inventory_dialog
            self.assertEqual([dialog.tabs.tabText(i) for i in range(dialog.tabs.count())],
                             ['网卡', '串口', '项目通道', '资源保护'])
            dialog.tabs.setCurrentIndex(3)
            self.wait_for(lambda: '没有活动租约' in dialog.resource_status.text())
            table = dialog.resource_table
            self.assertEqual(table.rowCount(), 0)
            self.assertEqual(table.editTriggers(), QAbstractItemView.EditTrigger.NoEditTriggers)

            def records():
                return {tuple(table.item(row, col).text() for col in range(table.columnCount()))
                        for row in range(table.rowCount())}

            owner_a, owner_b = 'native-power-owner', 'native-dut-owner'
            manager.acquire(owner_a, a.project_id, a.name, ('power:COM153',))
            try:
                manager.acquire(owner_b, b.project_id, b.name, ('dut:hardware:fixture-b', 'adb:4142'))
                try:
                    row_a = ('已持有', '串口 / 电源口', 'serial:com153', a.name, a.project_id, owner_a)
                    row_b = ('已持有', 'DUT', 'dut:hardware:fixture-b', b.name, b.project_id, owner_b)
                    row_adb = ('已持有', 'ADB', 'AB · adb:4142', b.name, b.project_id, owner_b)
                    self.wait_for(lambda: records() == {row_a, row_b, row_adb})
                    self.assertEqual(dialog.resource_status.text(), '已持有 3 条 · 待核实 0 条')
                    self.window.select_project(a.project_id)
                    table.selectRow(0)
                    self.window.select_project(b.project_id)
                    self.assertEqual(records(), {row_a, row_b, row_adb})
                    manager.release(owner_a, uncertain=True)
                    unknown = ('待核实', *row_a[1:])
                    self.wait_for(lambda: records() == {unknown, row_b, row_adb})
                    self.assertEqual(dialog.resource_status.text(), '已持有 2 条 · 待核实 1 条')
                    dialog.close()
                    self.window.sidebar_devices_button.click()
                    dialog = controller.device_inventory_dialog
                    table = dialog.resource_table
                    dialog.tabs.setCurrentIndex(3)
                    self.wait_for(lambda: records() == {unknown, row_b, row_adb})
                    self.assertIn(owner_a, manager.unknown_for(a.project_id))
                    self.assertIn(owner_b, manager.owners)
                finally:
                    manager.release(owner_b)
            finally:
                if owner_a in manager.owners:
                    manager.release(owner_a)
                if owner_a in manager.unknown_for(a.project_id):
                    manager.resolve(owner_a)
            self.wait_for(lambda: not records() and '没有活动租约' in dialog.resource_status.text())
            with patch.object(manager, 'hardware_error', '模拟保护不可用'):
                self.wait_for(lambda: '资源保护不可用' in dialog.resource_status.text())
                self.assertNotIn('没有活动租约', dialog.resource_status.text())
            self.wait_for(lambda: '没有活动租约' in dialog.resource_status.text())
            read.assert_not_called()
            dialog.close()

    def test_qt_manual_update_uses_verified_download_and_waits_for_cancel_cleanup(self):
        from unittest.mock import Mock
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from src.core.github_release_client import DownloadCancelled
        from src.services.app_update_service import AppUpdateService
        from test_app_update import ZIP_CONTENT, ZIP_HASH, release_payload

        app_update = self.controller.app_update
        client = Mock()
        client.latest_release.return_value = release_payload(version='v1.4.0')
        client.read_text_asset.return_value = ZIP_HASH + '  DUTPilot_portable.zip'
        app_update.worker.service_factory = lambda: AppUpdateService(client)
        self.assertTrue(self.window.settings_button.isEnabled())
        client.latest_release.assert_not_called()
        self.controller.update_action.trigger()
        self.wait_for(lambda: app_update.dialog is not None and app_update.dialog.update is not None)
        dialog = app_update.dialog
        self.assertIn('当前版本 1.3.0', dialog.summary.text())
        self.assertIn('v1.4.0', dialog.summary.text())
        self.assertIn('修复与新增功能', dialog.notes.toPlainText())
        self.assertIn('2026-10-16', dialog.release_date.text())
        self.assertFalse(dialog.progress.isTextVisible())
        self.assertLessEqual(dialog.height(), dialog.screen().availableGeometry().height())
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            QTest.qWait(60)
            self.assertTrue(dialog.grab().save(str(Path(output) / 'app-update-found.png')))

        destination = self.root / 'existing.zip'
        destination.write_bytes(b'keep original destination')
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(destination), 'ZIP')), \
                patch.object(QMessageBox, 'question', return_value=no) as confirm:
            dialog.primary.click()
            self.assertEqual(confirm.call_args.args[-1], no)
        client.download_asset.assert_not_called()

        def stream(data):
            def download(_url, path, _cancel, progress):
                path.write_bytes(data)
                progress(len(data), len(data))
            return download

        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(destination), 'ZIP')), \
                patch.object(QMessageBox, 'question', return_value=yes):
            client.download_asset.side_effect = stream(b'x' + ZIP_CONTENT[1:])
            dialog.primary.click()
            self.wait_for(lambda: 'SHA256 校验失败' in dialog.status.text())
            self.assertEqual(destination.read_bytes(), b'keep original destination')
            self.assertEqual(tuple(self.root.glob('.*.part')), ())
            client.download_asset.side_effect = stream(ZIP_CONTENT)
            dialog.primary.click()
            self.wait_for(lambda: dialog.saved_path == destination)
        self.assertEqual(destination.read_bytes(), ZIP_CONTENT)
        self.assertIn('SHA256 校验通过', dialog.status.text())
        self.assertEqual(dialog.progress.value(), 100)
        log_started, allow_write = threading.Event(), threading.Event()
        write_log = app_update.worker._write_log
        def slow_action_log(message):
            log_started.set()
            if not allow_write.wait(5):
                raise RuntimeError('fixture log was not released')
            write_log(message)
        with patch.object(QDesktopServices, 'openUrl', return_value=True) as open_folder, \
                patch.object(app_update.worker, '_write_log', side_effect=slow_action_log):
            try:
                dialog.primary.click()
                self.wait_for(log_started.is_set)
                self.assertEqual(Path(open_folder.call_args.args[0].toLocalFile()), self.root)
                ticks = []
                QTimer.singleShot(0, lambda: ticks.append(True))
                self.wait_for(lambda: bool(ticks))
                self.assertFalse(app_update.worker.finish_close())
            finally:
                allow_write.set()

        dialog.close()
        self.controller.update_action.trigger()
        self.wait_for(lambda: app_update.dialog is not None and app_update.dialog.update is not None)
        dialog = app_update.dialog
        pending = self.root / 'pending.zip'
        entered, stopping, release = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def cancellable(_url, path, cancel, progress):
            path.write_bytes(b'partial')
            progress(7, len(ZIP_CONTENT))
            entered.set()
            if cancel.wait(6):
                stopping.set()
            release.wait(6)
            raise DownloadCancelled('测试取消')

        client.download_asset.side_effect = cancellable
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(pending), 'ZIP')):
            dialog.primary.click()
        self.wait_for(lambda: entered.is_set() and dialog.progress.value() > 0)
        self.controller.submit('create', self.root / 'independent-project', '网络读取期间的项目')
        self.wait_for(lambda: len(self.window.projects) == 1)
        self.assertFalse(app_update.worker.idle)
        self.controller.request_close()
        self.wait_for(lambda: stopping.is_set() and self.controller.adapter.closed.is_set())
        self.assertTrue(self.window.isVisible())
        self.assertFalse(app_update.worker.idle)
        release.set()
        self.wait_for(lambda: app_update.worker.idle and not self.window.isVisible())
        self.assertFalse(pending.exists())
        self.assertEqual(tuple(self.root.glob('.*.part')), ())
        self.assertEqual(destination.read_bytes(), ZIP_CONTENT)
        log = (self.root / 'workspace' / 'workspace.log').read_text(encoding='utf-8')
        self.assertIn('操作已取消', log)
        self.assertIn('SHA256 校验失败', log)

    def test_native_new_project_dialog_calls_original_store_and_switches_without_tasks(self):
        from qt_project_wizard_probe import complete_new_dialog
        self.controller.new_project()
        complete_new_dialog(self, self.root / 'project-a', '真实临时项目A')
        self.wait_for(lambda: len(self.window.projects) == 1)
        first = self.window.projects[0]
        self.assertEqual(self.window.selected_project, first.project_id)
        self.assertTrue((self.root / 'project-a/project.linecheck.json').is_file())
        self.assertTrue(self.window.detail.start_button.isEnabled())
        self.assertEqual(first.active_task_count, 0)
        self.assertIn('create', self.window.logs.text.toPlainText())
        self.controller.submit('create', self.root / 'project-b', '真实临时项目B')
        self.wait_for(lambda: len(self.window.projects) == 2)
        self.window.select_project(first.project_id)
        self.controller.save_project()
        self.wait_for(lambda: 'save' in self.window.logs.text.toPlainText())
        self.window.show_dashboard()
        self.assertEqual([w.text() for w in self.window.dashboard.metric_numbers], ['2', '0', '0', '0', '0', '0'])
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            Path(output).mkdir(parents=True, exist_ok=True)
            self.assertTrue(self.window.grab().save(str(Path(output) / 'real-project-overview.png')))

    def test_qt_project_menu_shortcuts_and_directory_follow_selected_project(self):
        from PySide6.QtWidgets import QDialog, QFileDialog
        from qt_project_wizard_probe import complete_new_dialog

        menu = self.controller.menu
        menu.popup(self.window.mapToGlobal(QPoint(80, 80)))
        self.wait_for(menu.isVisible)
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            self.assertTrue(menu.grab().save(str(Path(output) / 'project-commands.png')))
        menu.hide()
        self.window.activateWindow()
        self.wait_for(self.window.isActiveWindow)
        self.assertFalse(self.controller.directory_action.isEnabled())
        ctrl = Qt.KeyboardModifier.ControlModifier
        first = self.root / '项目 A'
        QTest.keyClick(self.window, Qt.Key.Key_N, ctrl)
        complete_new_dialog(self, first, '项目 A')
        first_id = self.window.selected_project
        self.controller.submit('create', self.root / '项目 B', '项目 B')
        self.wait_for(lambda: len(self.window.projects) == 2)
        self.controller.submit('close', first_id)
        self.wait_for(lambda: len(self.window.projects) == 1)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(first / 'project.linecheck.json'), '')):
            QTest.keyClick(self.window, Qt.Key.Key_O, ctrl)
            self.wait_for(lambda: self.window.selected_project == first_id)
        with patch('os.startfile') as explorer:
            self.controller.directory_action.trigger()
            self.wait_for(lambda: explorer.called)
            explorer.assert_called_once_with(str(first), 'explore')
        with patch.object(self.controller, 'submit', wraps=self.controller.submit) as submit:
            QTest.keyClick(self.window, Qt.Key.Key_S, ctrl)
            submit.assert_called_once_with('save', first_id)
            dialog = QDialog(self.window)
            try:
                dialog.show()
                dialog.activateWindow()
                self.wait_for(dialog.isActiveWindow)
                QTest.keyClick(dialog, Qt.Key.Key_S, ctrl)
                self.assertEqual(submit.call_count, 1)
            finally:
                dialog.close()

    def test_qt_recent_menu_reopens_project_and_forgets_without_closing(self):
        from PySide6.QtWidgets import QFileDialog

        first_path = self.root / 'recent-a'
        self.controller.submit('create', first_path, '研发 & 测试')
        self.wait_for(lambda: len(self.window.projects) == 1)
        identifier = self.window.projects[0].project_id
        self.controller.submit('close', identifier)
        self.wait_for(lambda: not self.window.projects)
        self.controller.submit('create', self.root / 'recent-b', '回归项目')
        self.wait_for(lambda: len(self.window.projects) == 1 and len(self.controller._recent_projects) == 2)

        submenu = self.controller.recent_menu
        submenu.popup(self.window.mapToGlobal(QPoint(60, 60)))
        self.wait_for(submenu.isVisible)
        self.assertEqual([action.text() for action in submenu.actions()], ['回归项目', '研发 && 测试'])
        self.assertEqual(submenu.actions()[1].toolTip(), str(first_path))
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            Path(output).mkdir(parents=True, exist_ok=True)
            self.assertTrue(submenu.grab().save(str(Path(output) / 'recent-projects-menu.png')))
        with patch.object(QFileDialog, 'getOpenFileName', side_effect=AssertionError('recent opens saved path')):
            submenu.actions()[1].trigger()
            submenu.hide()
            self.wait_for(lambda: len(self.window.projects) == 2 and self.window.selected_project == identifier)
        self.assertEqual(self.window.projects[0].active_task_count, 0)
        self.controller.forget_recent_action.trigger()
        self.wait_for(lambda: len(self.controller._recent_projects) == 1)
        self.assertEqual(self.window.selected_project, identifier)
        self.assertEqual(len(self.window.projects), 2)
        self.assertTrue((first_path / 'project.linecheck.json').exists())

    def test_qt_session_manager_confirms_exact_batch_and_keeps_other_chat_input(self):
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        from src.models.ai_diagnostics import ProviderProfile
        from src.services.ai_case_store import open_shared_cases

        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-manage'), \
                patch('src.services.ai_case_store.open_shared_cases',
                      side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'manager-case-fixture')):
            self.controller.submit('create', self.root / 'chat-manager', '会话管理验证项目')
            self.wait_for(lambda: self.window.selected_project and self.window.ai_chat_action.isEnabled())
            identifier = self.window.selected_project
            workspace = self.controller.adapter._service
            workspace.models.save_profile(ProviderProfile(model='fixture-manager'), 'synthetic-manager-key')
            self.window.ai_chat_action.trigger()
            chat = self.controller.ai_chat
            self.wait_for(lambda: identifier in chat.windows and not chat.windows[identifier].busy)
            dialog = chat.windows[identifier]
            dialog.new_button.click()
            self.wait_for(lambda: not dialog.busy and bool(dialog.view.selected))
        active = dialog.view.selected
        store = self.controller.adapter._ai_chats[identifier].store
        record = store.chat(active)
        old_time = '2026-10-20 早班交接（旧格式时间，保留原文）'
        store.create_chat(dict(record, id='old-first', created=old_time, title='历史会话一'))
        store.create_chat(dict(record, id='old-second', created='2026-10-21T08:45:00', title='历史会话二'))
        for number in range(90):
            store.append_chat(active, {'role': 'user', 'text': f'长记录用于检查阅读位置 {number}'})
        dialog.composer.setPlainText('当前未发送内容')
        dialog.manage_button.click()
        manager = dialog.manager
        self.wait_for(lambda: not dialog.busy and manager.table.rowCount() == 3)
        self.assertEqual(manager._selected(), (active,))
        self.assertEqual(manager.counts.text(), '共 3 个会话，已选 1 个')
        transcript = dialog.transcript.toPlainText()
        vertical = dialog.transcript.verticalScrollBar()
        self.assertGreater(vertical.maximum(), 0)
        vertical.setValue(vertical.maximum() // 2)
        offset = vertical.value()
        manager.none_button.click()
        self.assertFalse(manager.delete_button.isEnabled())
        first, second = (list(manager.rows).index(key) for key in ('old-first', 'old-second'))
        self.assertEqual(manager.table.item(first, 0).text(), old_time)
        self.assertEqual(manager.table.item(first, 0).toolTip(), old_time)
        def select_row(row, modifiers=Qt.KeyboardModifier.NoModifier):
            index = manager.table.model().index(row, 1)
            point = manager.table.visualRect(index).center()
            QTest.mouseClick(manager.table.viewport(), Qt.MouseButton.LeftButton, modifiers, point)
        select_row(first)
        with patch.object(QInputDialog, 'getText', return_value=('更名后的历史会话', True)):
            manager.menu.actions()[0].trigger()
            self.wait_for(lambda: not manager.busy and manager.rows['old-first'].title == '更名后的历史会话')
        self.assertEqual(manager._selected(), ('old-first',))
        select_row(second, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(set(manager._selected()), {'old-first', 'old-second'})
        manager.resize(760, 460)
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            QTest.qWait(50)
            self.assertTrue(manager.grab().save(str(Path(output) / 'ai-session-manager.png')))
        def decline(prompt):
            self.assertEqual(prompt.defaultButton(), prompt.button(QMessageBox.StandardButton.No))
            self.assertEqual(prompt.escapeButton(), prompt.button(QMessageBox.StandardButton.No))
            self.assertIn('从「会话管理验证项目」永久删除以下 2 个会话', prompt.text())
            self.assertIn('更名后的历史会话', prompt.text())
            return QMessageBox.StandardButton.No
        with patch.object(QMessageBox, 'exec', autospec=True, side_effect=decline):
            manager.delete_button.click()
        self.assertEqual(manager.feedback.text(), '已取消删除')
        self.assertEqual(manager.table.rowCount(), 3)
        with patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Yes):
            manager.delete_button.click()
            self.wait_for(lambda: not manager.busy and manager.table.rowCount() == 1)
        self.assertEqual(dialog.view.selected, active)
        self.assertEqual(dialog.composer.toPlainText(), '当前未发送内容')
        self.assertEqual(dialog.transcript.toPlainText(), transcript)
        self.assertEqual(vertical.value(), offset)
        self.assertIn('已删除 2 个会话', manager.feedback.text())
        manager.select_button.click()
        self.assertEqual(manager._selected(), (active,))
        def add_during_confirmation(prompt):
            self.assertIn('永久删除以下 1 个会话', prompt.text())
            store.create_chat(dict(record, id='new-during-confirmation', created='2026-11-21T08:45:00', title='确认期间新增'))
            return QMessageBox.StandardButton.Yes
        with patch.object(QMessageBox, 'exec', autospec=True, side_effect=add_during_confirmation):
            manager.clear_button.click()
            self.wait_for(lambda: not manager.busy and dialog.view.selected == 'new-during-confirmation')
        self.assertEqual(set(manager.rows), {'new-during-confirmation'})
        self.assertFalse(dialog.composer.toPlainText())
        manager.refresh_button.click()
        self.wait_for(lambda: not manager.busy)
        self.assertEqual(manager.table.rowCount(), 1)
        manager.close()
        self.assertIsNone(dialog.manager)
        dialog.close()

    def test_pc_continuous_diagnosis_uses_local_scope_and_keeps_query_evidence(self):
        from dataclasses import replace
        from qt_execution_fakes import continue_chat_intent
        from src.core.ai_client import DiagnosticModelClient
        from src.models.ai_diagnostics import ModelReply, ProviderProfile
        from src.services.ai_case_store import open_shared_cases
        from src.services.ai_store import profile_fingerprint

        requests = []
        waiting_for_stop = threading.Event()
        def reply(client, history, tools, stop, on_text=None):
            requests.append({tool['name'] for tool in tools})
            if len(requests) > 2:
                waiting_for_stop.set()
                if stop.wait(10):
                    raise InterruptedError('模拟模型收到原停止事件')
                raise AssertionError('本机诊断未收到停止事件')
            if len(requests) == 1:
                calls = [dict(id='snapshot', name='read_pc_environment', arguments='{}'),
                         dict(id='unavailable', name='read_dut_state', arguments='{}')]
                turn = dict(role='assistant', content=None, tool_calls=[dict(id=c['id'], type='function',
                    function=dict(name=c['name'], arguments=c['arguments'])) for c in calls])
                return ModelReply('', calls, history + [turn])
            return ModelReply('模拟电脑取证完成', [], history + [dict(role='assistant', content='模拟电脑取证完成')])

        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'pc-legacy'), \
                patch('src.services.ai_case_store.open_shared_cases',
                      side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'pc-cases')), \
                patch.object(DiagnosticModelClient, 'complete', continue_chat_intent), \
                patch.object(DiagnosticModelClient, 'complete_stream', reply), \
                patch('src.services.ai_pc_conversation.read_network_state',
                      side_effect=lambda category, *_: 'fixture-' + category) as readings, \
                patch('src.services.project_diagnostic_transport.ProjectDiagnosticTransport.open', side_effect=AssertionError('DUT I/O')) as device:
            self.controller.submit('create', self.root / 'pc-project', '本机取证项目')
            self.wait_for(lambda: len(self.window.projects) == 1 and self.window.ai_chat_action.isEnabled())
            project = self.window.selected_project
            models = self.controller.adapter._service.models
            profile = models.save_profile(ProviderProfile(model='pc-fixture', context_tokens=65536), 'fixture-key')
            models.save_profile(replace(profile, capability='可自动诊断', tested_fingerprint=profile_fingerprint(profile)))
            self.window.ai_chat_action.trigger()
            windows = self.controller.ai_chat.windows
            self.wait_for(lambda: project in windows and not windows[project].busy)
            dialog = windows[project]
            self.assertIn(dialog.new_pc_action, dialog.new_button.menu().actions())
            self.assertGreaterEqual(dialog.new_button.height(), dialog.manage_button.height())
            self.assertEqual(dialog.new_button.width(), dialog.manage_button.width())
            dialog.new_pc_action.trigger()
            self.wait_for(lambda: dialog.view.pc_diagnosis and not dialog.busy)
            selected = dialog.view.selected
            original = self.controller.adapter._ai_chats[project].store
            record = original.chat(selected)
            self.assertEqual((record['scope'], record['target'], record['diagnosis_only']), ('pc', None, True))
            self.assertIn('只读取证', dialog.status.text())
            readings.assert_not_called()
            dialog.composer.setPlainText('查询本机环境')
            QTest.mouseClick(dialog.send_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: '模拟电脑取证完成' in dialog.transcript.toPlainText() and not dialog.view.running)
            self.assertEqual([item.args[0] for item in readings.call_args_list], ['addresses', 'route', 'wifi'])
            device.assert_not_called()
            self.assertIn('read_pc_environment', requests[0])
            self.assertFalse(requests[0] & {'run_local_command', 'write_local_file', 'read_dut_state'})
            self.assertIn('fixture-route', repr(original.chat_evidence(selected)))
            dialog.close()
            self.wait_for(lambda: project not in windows)
            self.window.ai_chat_action.trigger()
            self.wait_for(lambda: project in windows and not windows[project].busy)
            self.assertEqual(windows[project].view.selected, selected)
            self.assertTrue(windows[project].view.pc_diagnosis)
            self.assertEqual(readings.call_count, 3)
            output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if output:
                self.assertTrue(windows[project].grab().save(str(Path(output) / 'pc-diagnosis.png')))

            dialog = windows[project]
            dialog.composer.setPlainText('继续核对')
            QTest.mouseClick(dialog.send_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: waiting_for_stop.is_set() and dialog.stop_button.isEnabled()
                          and not dialog.view.routing and not dialog.busy)
            dialog.composer.setPlainText('补充当前现象')
            self.assertTrue(dialog.send_button.isEnabled())
            QTest.mouseClick(dialog.send_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not dialog.busy and not dialog.view.routing
                          and '补充当前现象' in dialog.transcript.toPlainText()
                          and any(message['role'] == 'user' and message['text'] == '补充当前现象'
                                  for message in original.chat_items(selected)))
            QTest.mouseClick(dialog.stop_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not dialog.busy and not dialog.view.running)
            self.assertEqual((len(requests), readings.call_count), (3, 3))
            execution = self.controller.adapter._executions[project]
            chat = self.controller.adapter._ai_chats[project]
            self.assertIs(chat.conversation.context, execution.ai_evidence)
            waiting_for_stop.clear()
            dialog.composer.setPlainText('等待批次切换')
            QTest.mouseClick(dialog.send_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: waiting_for_stop.is_set() and dialog.stop_button.isEnabled())
            execution.observe_ai_event(dict(type='diagnostic_start', run_id='next-fixture-run'))
            self.wait_for(lambda: not dialog.view.running)
            self.assertTrue(any('新批次已开始' in message['text'] for message in original.chat_items(selected)))
            self.assertFalse(chat.conversation.collection_status(selected)['enabled'])
            dialog.new_pc_action.trigger()
            self.wait_for(lambda: not dialog.busy and dialog.view.selected != selected)
            self.assertEqual(original.chat(dialog.view.selected)['run_id'], 'next-fixture-run')
            self.assertTrue(chat.conversation.collection_status(dialog.view.selected)['enabled'])
            self.assertEqual(readings.call_count, 3)

    def test_qt_periodic_refresh_reports_read_failure_without_blocking_other_actions(self):
        from PySide6.QtWidgets import QMessageBox

        self.controller.submit('create', self.root / 'refresh', '自动刷新的模拟项目')
        self.wait_for(lambda: len(self.window.projects) == 1 and self.window.selected_project)
        selected = self.window.selected_project
        adapter = self.controller.adapter
        dirty = adapter._service.projects.dirty
        failures = []
        refreshes = []
        take_updates = adapter.take_updates

        def fail_once(context):
            if not failures:
                failures.append(context.identity.project_id)
                raise PermissionError('simulated read sharing violation')
            return dirty(context)

        def observe():
            projects, logs, results = take_updates()
            refreshes.extend(r.error for r in results if r.operation == 'refresh')
            return projects, logs, results

        with patch.object(adapter._service.projects, 'dirty', side_effect=fail_once), \
                patch.object(adapter, 'take_updates', side_effect=observe), \
                patch.object(QMessageBox, 'warning', return_value=QMessageBox.StandardButton.Ok) as modal:
            self.wait_for(lambda: any(refreshes) and '自动刷新失败' in self.window.statusBar().currentMessage())
            self.assertEqual(failures, [selected])
            self.assertEqual(self.window.selected_project, selected)
            self.assertEqual([p.project_id for p in self.window.projects], [selected])
            self.wait_for(lambda: refreshes and not refreshes[-1])
            modal.assert_not_called()
            self.controller.submit('open', self.root / 'missing-project')
            self.wait_for(lambda: modal.called)
            self.assertIn('项目操作未完成', modal.call_args.args)
            self.assertEqual(self.window.selected_project, selected)

    def test_qt_chat_reads_only_the_open_project_serial_monitor(self):
        from contextlib import ExitStack
        from dataclasses import replace
        from functools import partial
        from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
        from qt_serial_fakes import SerialHarness
        from src.core.ai_client import DiagnosticModelClient
        from src.models.ai_diagnostics import ModelReply, ProviderProfile
        from src.models.serial_models import SerialSettings
        from src.services.ai_case_store import open_shared_cases
        from src.services.ai_diagnostic_service import AiDiagnosticService
        from src.services.ai_store import profile_fingerprint

        marker = 'SERIAL-RX-7963'
        offered = []

        class Client(DiagnosticModelClient):
            from qt_execution_fakes import continue_chat_intent as complete

            def complete_stream(self, history, tools, stop, on_text=None):
                offered.append({tool['name'] for tool in tools})
                if len(offered) == 1:
                    return ModelReply('', [dict(id='fixture-read', name='read_serial_log', arguments={})], history)
                if marker not in str(history):
                    raise AssertionError('串口输出未送达模拟模型')
                answer = '本次读取到模拟串口输出 ' + marker
                return ModelReply(answer, [], history + [dict(role='assistant', content=answer)])

        with ExitStack() as guards:
            guards.enter_context(patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'models'))
            guards.enter_context(patch('src.services.ai_case_store.open_shared_cases',
                side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'cases')))
            guards.enter_context(patch('src.services.qt_ai_chat.AiDiagnosticService',
                side_effect=partial(AiDiagnosticService, client_factory=Client)))
            physical = guards.enter_context(patch('serial.Serial', side_effect=AssertionError('physical serial')))
            harness = SerialHarness().start()
            guards.callback(harness.stop)
            self.controller.submit('create', self.root / 'serial-chat', '串口材料')
            self.wait_for(lambda: len(self.window.projects) == 1 and self.window.ai_chat_action.isEnabled())
            project = self.window.selected_project
            adapter = self.controller.adapter
            service = adapter._service
            ctx = service.projects.opened[project]
            port = 'COM7963'
            ChannelConfigStore(ctx.config_dir / 'network_card_ip.ini').save([ChannelConfig('channel_7',
                enabled=True, serial_port=port, vlan_name='VLAN107', network_card_ip='192.0.2.7', device_manage_ip='192.0.2.1')])
            profile = service.models.save_profile(ProviderProfile(model='fixture', context_tokens=65536), 'fixture-key')
            service.models.save_profile(replace(profile, capability='可自动诊断', tested_fingerprint=profile_fingerprint(profile)))
            self.controller.submit('serial_show', project)
            self.wait_for(lambda: project in adapter._executions and adapter._executions[project].terminal is not None)
            manager = adapter._executions[project].manager
            session = manager.acquire_monitor('fixture', SerialSettings(port))
            guards.callback(manager.release, 'fixture', port, wait=True)
            harness.drivers[port].input.put(marker.encode('ascii'))
            self.wait_for(lambda: session.cursor() == len(marker))
            self.window.ai_chat_action.trigger()
            windows = self.controller.ai_chat.windows
            self.wait_for(lambda: project in windows and not windows[project].busy)
            dialog = windows[project]
            QTest.mouseClick(dialog.new_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: dialog.view and dialog.view.selected and not dialog.busy)
            dialog.composer.setPlainText('通道7 读取这条串口的近期输出')
            QTest.mouseClick(dialog.send_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: marker in dialog.transcript.toPlainText() and not dialog.view.running)
            self.assertIn('可读取已打开串口', dialog.status.text())
            self.assertTrue(dialog.view.passive_serial)
            self.assertEqual(offered[0], {'ask_user', 'read_test_evidence', 'read_serial_log'})
            self.assertEqual(manager.existing_session(SerialSettings(port)), session)
            self.assertFalse(harness.drivers[port].writes)
            physical.assert_not_called()
            out = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if out:
                self.assertTrue(dialog.grab().save(str(Path(out) / 'ai-passive-serial.png')))
            dialog.permission_action.trigger()
            self.wait_for(lambda: dialog.progress_dialog is not None and not dialog.busy)
            self.assertIn('本会话实时取证：仅可读取已打开的本项目串口', dialog.progress_text.toPlainText())

    def test_qt_chat_switches_to_configured_local_channel_without_model_or_device(self):
        from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
        from src.models.ai_diagnostics import ProviderProfile
        from src.services.ai_case_store import open_shared_cases

        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'models'), \
                patch('src.services.ai_case_store.open_shared_cases',
                      side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'cases')):
            self.controller.submit('create', self.root / 'channel', '通道路由')
            self.wait_for(lambda: len(self.window.projects) == 1 and self.window.ai_chat_action.isEnabled())
            project = self.window.selected_project
            service = self.controller.adapter._service
            config = service.projects.opened[project].config_dir / 'network_card_ip.ini'
            ChannelConfigStore(config).save([ChannelConfig('channel_7', enabled=True, vlan_name='VLAN107',
                serial_port='COM7963', network_card_ip='192.0.2.7', device_manage_ip='192.0.2.1')])
            service.models.save_profile(ProviderProfile(model='fixture', context_tokens=65536), 'fixture-key')
            self.window.ai_chat_action.trigger()
            chat = self.controller.ai_chat
            self.wait_for(lambda: project in chat.windows and not chat.windows[project].busy)
            dialog = chat.windows[project]
            QTest.mouseClick(dialog.new_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: dialog.view and dialog.view.selected and not dialog.busy)
            general = dialog.view.selected
            backend = self.controller.adapter._ai_chats[project]
            with patch.object(backend.conversation, 'send', side_effect=AssertionError('仅切换会话')) as submit, \
                    patch.object(backend.diagnostic, 'client_factory', side_effect=AssertionError('无需模型识别')) as model:
                dialog.composer.setPlainText('切换到通道7')
                QTest.mouseClick(dialog.send_button, Qt.MouseButton.LeftButton)
                self.wait_for(lambda: not dialog.busy and dialog.view.selected != general)
                self.assertIn('通道7', dialog.status.text().replace(' ', ''))
                self.assertIn('仅分析留存材料', dialog.status.text())
                self.assertEqual(dialog.composer.toPlainText(), '')
                self.assertFalse(dialog.stop_button.isEnabled())
                self.assertTrue(dialog.view.writable)
                self.assertEqual(backend.store.chat(dialog.view.selected)['target']['port'], 'COM7963')
                output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
                if output:
                    self.assertTrue(dialog.grab().save(str(Path(output) / 'ai-local-channel-switch.png')))
                submit.assert_not_called()
                model.assert_not_called()

            import json
            import threading
            from src.core.ai_client import DiagnosticModelClient
            from src.models.ai_diagnostics import ModelReply
            from src.services.ai_session_router import ROUTE_INSTRUCTIONS

            entered, release = threading.Event(), threading.Event()
            channel_session = dialog.view.selected
            intents = []

            class Client(DiagnosticModelClient):
                def complete(self, history, tools, stop):
                    assert history[0]['content'] == ROUTE_INSTRUCTIONS and not tools
                    request = json.loads(history[1]['content'])
                    intents.append(request['message'])
                    entered.set()
                    assert release.wait(6)
                    if request['message'].startswith('模拟识别失败'):
                        return ModelReply('invalid-json', [], history)
                    return ModelReply(json.dumps(dict(intent='switch', scope='device', channel=7,
                        question='', clarification='')), [], history)

            with patch.object(backend.diagnostic, 'client_factory', Client), \
                    patch.object(backend.conversation, 'send', side_effect=AssertionError('仅切换会话')) as submit:
                QTest.mouseClick(dialog.new_button, Qt.MouseButton.LeftButton)
                self.wait_for(lambda: not dialog.busy and dialog.view.selected != channel_session)
                question = '请把排查对象换到七号测试位'
                try:
                    dialog.composer.setPlainText(question)
                    QTest.mouseClick(dialog.send_button, Qt.MouseButton.LeftButton)
                    self.wait_for(lambda: entered.is_set() and dialog.view.routing and not dialog.busy)
                    self.assertIn('正在识别会话目标', dialog.status.text())
                    self.assertTrue(dialog.stop_button.isEnabled())
                    self.assertEqual(dialog.view.messages[-1].text, question)
                    if output:
                        self.assertTrue(dialog.grab().save(str(Path(output) / 'ai-natural-target-pending.png')))
                finally:
                    release.set()
                self.wait_for(lambda: not dialog.view.routing and dialog.view.selected == channel_session)
                self.assertIn('通道7', dialog.status.text().replace(' ', ''))
                self.assertEqual(intents, [question])
                for suffix, replacement in [('重试', ''), ('保留新输入', '手工输入的下一条')]:
                    entered.clear()
                    release.clear()
                    failed = '模拟识别失败' + suffix
                    try:
                        dialog.composer.setPlainText(failed)
                        QTest.mouseClick(dialog.send_button, Qt.MouseButton.LeftButton)
                        self.wait_for(lambda: entered.is_set() and dialog.view.routing and not dialog.busy)
                        if replacement:
                            dialog.composer.setPlainText(replacement)
                    finally:
                        release.set()
                    self.wait_for(lambda: dialog.view.retry_input == failed and not dialog.view.routing)
                    self.assertEqual(dialog.composer.toPlainText(), replacement or failed)
                    self.assertIn('目标识别失败', dialog.latest_status.text())
                submit.assert_not_called()

    def test_qt_ai_chat_sends_and_reopens_original_persisted_history(self):
        from functools import partial
        from src.core.ai_client import DiagnosticModelClient
        from src.models.ai_diagnostics import ModelReply, ProviderProfile
        from src.services.ai_case_store import open_shared_cases
        from src.services.ai_diagnostic_service import AiDiagnosticService

        release = threading.Event()
        self.addCleanup(release.set)

        class Client(DiagnosticModelClient):
            from qt_execution_fakes import continue_chat_intent as complete

            def complete_stream(self, history, tools, stop, on_text=None):
                if tools:
                    raise AssertionError('ordinary question and answer must not receive tools')
                on_text('合成回复片段')
                if not release.wait(6) or stop.is_set():
                    raise InterruptedError('界面验证超时或取消')
                reply = '合成回复结果'
                return ModelReply(reply, [], history + [dict(role='assistant', content=reply)])

        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-chat'), \
                patch('src.services.ai_case_store.open_shared_cases',
                      side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'chat-case-fixture')), \
                patch('src.services.qt_ai_chat.AiDiagnosticService', side_effect=partial(AiDiagnosticService, client_factory=Client)):
            self.controller.submit('create', self.root / 'chat-a', 'AI 会话项目 A')
            self.wait_for(lambda: len(self.window.projects) == 1 and self.window.ai_chat_action.isEnabled())
            first = self.window.selected_project
            self.controller.adapter._service.models.save_profile(
                ProviderProfile(model='fixture-chat', context_tokens=65536), 'synthetic-chat-key')
            self.assertEqual(self.window.ai_chat_action.text(), 'Ai助手')
            self.assertEqual(self.window.detail.tabs.tabText(8), 'Ai助手')
            self.window.ai_chat_action.trigger()
            chat = self.controller.ai_chat
            self.wait_for(lambda: first in chat.windows and not chat.windows[first].busy)
            dialog = chat.windows[first]
            self.assertFalse(dialog.send_button.isEnabled())
            self.assertEqual(dialog.windowTitle(), 'Ai助手 · AI 会话项目 A')
            self.assertLessEqual(dialog.width(), dialog.screen().availableGeometry().width())
            self.assertLessEqual(dialog.height(), dialog.screen().availableGeometry().height())
            QTest.mouseClick(dialog.new_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: dialog.view is not None and dialog.view.selected and not dialog.busy)
            chosen = dialog.view.selected
            dialog.composer.setPlainText('合成测试问题')
            self.assertTrue(dialog.send_button.isEnabled(), dialog.status.text())
            QTest.mouseClick(dialog.send_button, Qt.MouseButton.LeftButton)
            try:
                self.wait_for(lambda: dialog.feedback.text() or
                    ('合成回复片段' in dialog.transcript.toPlainText() and dialog.stop_button.isEnabled()) or
                    (not dialog.busy and dialog.view.messages and not dialog.view.running))
                self.assertFalse(dialog.feedback.text(), dialog.feedback.text())
                self.assertIn('合成回复片段', dialog.transcript.toPlainText())
                self.assertTrue(dialog.stop_button.isEnabled())
                dialog.close()
                self.wait_for(lambda: first not in chat.windows)
                self.window.detail.tabs.setCurrentIndex(8)
                self.wait_for(lambda: first in chat.windows and not chat.windows[first].busy)
                dialog = chat.windows[first]
                self.assertEqual(dialog.view.selected, chosen)
            finally:
                release.set()
            self.wait_for(lambda: '合成回复结果' in dialog.transcript.toPlainText() and not dialog.stop_button.isEnabled())
            self.assertIn('合成测试问题', dialog.transcript.toPlainText())
            self.assertNotIn('合成回复片段', dialog.transcript.toPlainText())
            self.assertIn('65,536', dialog.usage.text())
            self.assertEqual(dialog.composer.toPlainText(), '')
            output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if output:
                self.assertTrue(dialog.grab().save(str(Path(output) / 'ai-chat-window.png')))
            self.assertTrue(dialog.progress_action.isEnabled())
            dialog.permission_action.trigger()
            self.wait_for(lambda: dialog.progress_dialog is not None and not dialog.busy)
            self.assertIn('会话权限', dialog.progress_dialog.windowTitle())
            self.assertIn('本会话实时取证：不可用', dialog.progress_text.toPlainText())
            dialog.review_action.trigger()
            self.wait_for(lambda: not dialog.busy and '没有待确认操作' in dialog.feedback.text())
            from PySide6.QtWidgets import QPushButton
            review = dict(session_id=chosen, id='fixture-action', fingerprint='fixture-fingerprint',
                          scope='pc', target=None, name='模拟查询', assessment={'reason': '人工确认'},
                          params={'资源': '测试夹具'})
            with patch.object(dialog, '_submit') as submit:
                dialog.review_action_result(chosen, review)
                if output:
                    self.assertTrue(dialog.review_dialog.grab().save(str(Path(output) / 'session-approval.png')))
                dialog.review_dialog.close()
                submit.assert_not_called()
                for decision, title in ((False, '拒绝'), (True, '批准本次操作')):
                    dialog.review_action_result(chosen, review)
                    controls = {b.text(): b for b in dialog.review_dialog.findChildren(QPushButton)}
                    controls[title].click()
                    submit.assert_called_with('ai_chat_decide', chosen, 'fixture-action', 'fixture-fingerprint', decision)
            dialog.progress_action.trigger()
            self.wait_for(lambda: dialog.progress_dialog is not None and not dialog.busy)
            retained = dialog.progress_dialog
            self.assertTrue(dialog.progress_text.isReadOnly())
            self.assertIn('本会话尚未开始连续诊断', dialog.progress_text.toPlainText())
            store = self.controller.adapter._model_settings.stores[first]
            store.update_chat(chosen, diagnostic_task=dict(goal='核对留存材料', steps=[dict(status='completed', text='原步骤')],
                checks=[dict(tool='原检查', evidence_id='历史证据', failed=True)], findings=[], reason='已停止'))
            dialog.progress_action.trigger()
            self.wait_for(lambda: not dialog.busy and '已检查：原步骤' in dialog.progress_text.toPlainText())
            self.assertIs(dialog.progress_dialog, retained)
            self.assertLessEqual(retained.width(), retained.screen().availableGeometry().width())
            self.assertLessEqual(retained.height(), retained.screen().availableGeometry().height())
            self.assertIn('历史证据（失败/受阻）', dialog.progress_text.toPlainText())
            self.assertIn('结束原因：已停止', dialog.progress_text.toPlainText())
            if output:
                self.assertTrue(retained.grab().save(str(Path(output) / 'ai-chat-progress.png')))
            dialog.composer.setPlainText('未发送的草稿')
            QTest.mouseClick(dialog.new_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not dialog.busy and dialog.view.selected != chosen)
            self.assertEqual(dialog.composer.toPlainText(), '未发送的草稿')
            self.assertIsNone(dialog.progress_dialog)
            dialog.show_progress(chosen, '过期回执')
            dialog.show_permissions(chosen, '旧偏好', '旧权限', False)
            self.assertIsNone(dialog.progress_dialog)
            self.assertNotIn('合成回复结果', dialog.transcript.toPlainText())
            self.controller.submit('create', self.root / 'chat-b', 'AI 会话项目 B')
            self.wait_for(lambda: len(self.window.projects) == 2 and self.window.selected_project != first)
            second = self.window.selected_project
            self.window.ai_chat_action.trigger()
            self.wait_for(lambda: second in chat.windows and not chat.windows[second].busy)
            self.assertFalse(chat.windows[second].view.sessions)
            self.assertFalse(chat.windows[second].progress_action.isEnabled())
            self.assertFalse(chat.windows[second].permission_action.isEnabled())
            self.assertEqual(chat.windows[second].composer.toPlainText(), '')
            dialog.sessions.setCurrentRow(1)
            self.wait_for(lambda: not dialog.busy and dialog.view.selected == chosen)
            self.assertIn('合成回复结果', dialog.transcript.toPlainText())
            dialog.progress_action.trigger()
            self.wait_for(lambda: dialog.progress_dialog is not None and not dialog.busy)
            self.assertIn('已检查：原步骤', dialog.progress_text.toPlainText())
            dialog.close()
            self.wait_for(lambda: first not in chat.windows)

    def test_qt_ai_report_confirmation_binds_the_project_and_report_ids(self):
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        from src.services.ai_case_store import open_shared_cases

        chat = self.controller.ai_chat
        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-reports'), \
                patch('src.services.ai_case_store.open_shared_cases',
                      side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'report-case-fixture')):
            self.controller.submit('create', self.root / 'reports-a', '诊断报告项目 A')
            self.wait_for(lambda: len(self.window.projects) == 1 and self.window.ai_chat_action.isEnabled())
            first = self.window.selected_project
            self.window.ai_chat_action.trigger()
            self.wait_for(lambda: first in chat.windows and not chat.windows[first].busy)
            first_chat = chat.windows[first]
            store = self.controller.adapter._model_settings.stores[first]
            payload = dict(report='## 原始分析\n<img src="https://invalid.example/fixture">',
                           evidence='[1] 原始证据', question='合成诊断报告', channel=3, provider='fixture',
                           model='fixture-model', status='完成')
            store.save_report('fixture-report-a', payload)
            sample = ('已观察事实\n第 24 轮启动后，通道 3 的连通性检查超时。\n\n本地证据\n'
                      '串口记录包含启动完成标记，检查结果仍为超时。\n\n建议检查\n核对该通道的网卡绑定和检查时间。')
            store.save_report('fixture-report-b', dict(payload, question='第 24 轮连通性样例', report=sample))
            QTest.mouseClick(first_chat.reports_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: first in chat.report_windows and bool(chat.report_windows[first].rows))
            dialog = chat.report_windows[first]
            self.assertEqual(dialog.project_id, first)
            self.assertFalse(dialog.busy)
            self.assertLessEqual(dialog.height(), dialog.screen().availableGeometry().height())
            first_chat.close()
            self.assertTrue(dialog.isVisible())

            items = {dialog.reports.item(row).data(Qt.ItemDataRole.UserRole): dialog.reports.item(row)
                     for row in range(dialog.reports.count())}
            QTest.mouseClick(dialog.reports.viewport(), Qt.MouseButton.LeftButton,
                             pos=dialog.reports.visualItemRect(items['fixture-report-a']).center())
            self.wait_for(lambda: not dialog.busy and dialog.detail.identifier == 'fixture-report-a')
            self.assertEqual(dialog.reports.selectedItems(), [items['fixture-report-a']])
            self.assertEqual(dialog.analysis.toPlainText(), payload['report'])
            self.assertEqual(dialog.evidence.toPlainText(), payload['evidence'])

            active = dialog.detail.identifier
            with patch.object(QInputDialog, 'getText', return_value=('显示名称', True)):
                dialog.rename_action.trigger()
                self.wait_for(lambda: dialog.rows[active].title == '显示名称')
            self.assertEqual(store.report(active)['report'], payload['report'])
            display = next(dialog.reports.item(row) for row in range(dialog.reports.count())
                           if dialog.reports.item(row).data(Qt.ItemDataRole.UserRole) == 'fixture-report-b')
            QTest.mouseClick(dialog.reports.viewport(), Qt.MouseButton.LeftButton,
                             pos=dialog.reports.visualItemRect(display).center())
            self.wait_for(lambda: not dialog.busy and dialog.analysis.toPlainText() == sample)
            QTest.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not dialog.busy)
            self.assertEqual(dialog.detail.identifier, 'fixture-report-b')
            output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if output:
                self.assertTrue(dialog.grab().save(str(Path(output) / 'ai-diagnostic-reports.png')))

            def decline(prompt):
                self.assertEqual(prompt.defaultButton(), prompt.button(QMessageBox.StandardButton.No))
                self.assertIn('诊断报告项目 A', prompt.text())
                self.assertIn('fixture-report-a', prompt.text())
                self.assertIn('fixture-report-b', prompt.text())
                return QMessageBox.StandardButton.No

            with patch.object(QMessageBox, 'exec', new=decline):
                dialog.clear_action.trigger()
            self.assertEqual(dialog.feedback.text(), '已取消删除')
            self.assertEqual(len(store.reports()), 2)

            self.controller.submit('create', self.root / 'reports-b', '诊断报告项目 B')
            self.wait_for(lambda: len(self.window.projects) == 2 and self.window.selected_project != first)
            second = self.window.selected_project
            self.window.ai_chat_action.trigger()
            self.wait_for(lambda: second in chat.windows and not chat.windows[second].busy)
            other = self.controller.adapter._model_settings.stores[second]
            other.save_report('fixture-report-a', dict(payload, report='项目 B 分析'))

            def approve(prompt):
                self.assertIn('诊断报告项目 A', prompt.text())
                store.save_report('arrived-during-confirmation', payload)
                return QMessageBox.StandardButton.Yes

            with patch.object(QMessageBox, 'exec', new=approve):
                dialog.clear_action.trigger()
            self.wait_for(lambda: set(dialog.rows) == {'arrived-during-confirmation'} and not dialog.busy)
            self.assertEqual(dialog.feedback.text(), '已删除 2 份报告')
            self.assertEqual(other.report('fixture-report-a')['report'], '项目 B 分析')
            self.controller.submit('close', first)
            self.wait_for(lambda: first not in chat.report_windows and len(self.window.projects) == 1)

    def test_qt_ai_report_handoff_confirms_legacy_target_without_sending(self):
        from dataclasses import asdict
        from PySide6.QtWidgets import QComboBox, QDialogButtonBox
        from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
        from src.models.ai_diagnostics import DiagnosticTarget, ProviderProfile
        from src.services.ai_case_store import open_shared_cases

        chat = self.controller.ai_chat
        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-handoff'), \
                patch('src.services.ai_case_store.open_shared_cases',
                      side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'handoff-case-fixture')), \
                patch('src.services.ai_conversation_service.AiConversationService.send', side_effect=AssertionError('handoff must not send')) as send, \
                patch('src.services.ai_diagnostic_service.AiDiagnosticService.submit', side_effect=AssertionError('handoff must not collect')) as collect:
            self.controller.submit('create', self.root / 'handoff-a', '接手报告项目 A')
            self.wait_for(lambda: len(self.window.projects) == 1 and self.window.ai_chat_action.isEnabled())
            first = self.window.selected_project
            workspace = self.controller.adapter._service
            workspace.models.save_profile(ProviderProfile(model='handoff-fixture'), 'synthetic-handoff-key')
            self.window.ai_chat_action.trigger()
            self.wait_for(lambda: first in chat.windows and not chat.windows[first].busy)
            store = self.controller.adapter._model_settings.stores[first]
            config = ChannelConfigStore(workspace.projects.opened[first].config_dir / 'network_card_ip.ini')
            config.save([ChannelConfig('channel_7', vlan_name='vlan107', network_card_ip='192.0.2.10',
                                       device_manage_ip='192.0.2.1')])
            original = DiagnosticTarget(7, 'vlan142', 'COM42', '192.0.2.88', '192.0.2.2')
            store.save_report('snap-fixture', dict(report='带快照的合成报告', channel=7, target=asdict(original)))
            store.save_report('old-fixture', dict(report='旧报告合成分析', channel=7))
            chat.windows[first].reports_button.click()
            self.wait_for(lambda: first in chat.report_windows and chat.report_windows[first].detail is not None)
            report = chat.report_windows[first]
            items = {report.reports.item(row).data(Qt.ItemDataRole.UserRole): report.reports.item(row)
                     for row in range(report.reports.count())}
            report.reports.setCurrentItem(items['old-fixture'])
            self.wait_for(lambda: not report.busy and report.detail.identifier == 'old-fixture')
            chat.windows[first].close()
            report.handoff_button.click()
            self.wait_for(lambda: report.handoff_confirmation is not None)
            prompt = report.handoff_confirmation
            target = prompt.findChild(QComboBox)
            buttons = prompt.findChild(QDialogButtonBox)
            cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
            self.assertEqual(target.currentIndex(), 0)
            self.assertTrue(cancel.isDefault())
            self.assertFalse(buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())
            cancel.click()
            self.wait_for(lambda: report.feedback.text() == '已取消关联')
            self.assertEqual(store.chats(), [])

            report.handoff_button.click()
            self.wait_for(lambda: report.handoff_confirmation is not None)
            prompt = report.handoff_confirmation
            target = prompt.findChild(QComboBox)
            self.assertIn('COM7', target.itemText(1))
            target.setCurrentIndex(1)
            output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if output:
                self.assertTrue(prompt.grab().save(str(Path(output) / 'ai-report-handoff.png')))
            prompt.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
            self.wait_for(lambda: first in chat.windows and chat.windows[first].view is not None and not chat.windows[first].busy)
            session = chat.windows[first]
            self.assertFalse(session.send_button.isEnabled())
            self.assertEqual(store.chat(session.view.selected)['source_report_id'], 'old-fixture')
            report.reports.setCurrentItem(items['snap-fixture'])
            self.wait_for(lambda: not report.busy and report.detail.identifier == 'snap-fixture')
            report.handoff_button.click()
            self.wait_for(lambda: store.chat(session.view.selected)['source_report_id'] == 'snap-fixture')
            self.assertIsNone(report.handoff_confirmation)
            self.assertEqual(store.chat(session.view.selected)['target'], asdict(original))
            send.assert_not_called()
            collect.assert_not_called()

    def test_qt_reopens_local_device_chat_from_an_older_power_run(self):
        from dataclasses import asdict
        from functools import partial
        from src.core.ai_client import DiagnosticModelClient
        from src.models.ai_diagnostics import DiagnosticTarget, ModelReply, ProviderProfile
        from src.services.ai_case_store import open_shared_cases
        from src.services.ai_diagnostic_service import AiDiagnosticService

        requests = []

        class Client(DiagnosticModelClient):
            def complete_stream(self, history, tools, stop, on_text=None):
                requests.append(history)
                reply = '旧批次串口曾报告链路中断，需结合当时日志核对。'
                return ModelReply(reply, [], history + [dict(role='assistant', content=reply)])

        chat = self.controller.ai_chat
        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'old-models'), \
                patch('src.services.ai_case_store.open_shared_cases',
                      side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'old-cases')), \
                patch('src.services.qt_ai_chat.AiDiagnosticService',
                      side_effect=partial(AiDiagnosticService, client_factory=Client)):
            self.controller.submit('create', self.root / 'old-device', '设备历史项目')
            self.wait_for(lambda: len(self.window.projects) == 1 and self.window.ai_chat_action.isEnabled())
            project = self.window.selected_project
            profile = self.controller.adapter._service.models.save_profile(
                ProviderProfile(model='历史分析模拟模型', context_tokens=65536), 'synthetic')
            self.window.ai_chat_action.trigger()
            self.wait_for(lambda: project in chat.windows and not chat.windows[project].busy)
            service = self.controller.adapter._ai_chats[project]
            store = service.store
            identifier = 'old-device-session'
            row = dict(id=identifier, created='2026-11-01 09:00:00', title='通道 7 上次挂测',
                       target=asdict(DiagnosticTarget(7, 'vlan107', 'COM7', '192.0.2.10', '192.0.2.1')),
                       profile=asdict(profile), settings={}, run_id='previous-power-run', status='可继续', pending=None)
            store.create_chat(row)
            service.conversation.add_evidence(identifier, '原串口留存日志', '已留存链路中断')
            chat.windows[project].close()
            self.wait_for(lambda: project not in chat.windows)
            self.window.ai_chat_action.trigger()
            self.wait_for(lambda: project in chat.windows and chat.windows[project].sessions.count() > 0)
            dialog = chat.windows[project]
            for i in range(dialog.sessions.count()):
                item = dialog.sessions.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == identifier:
                    dialog.sessions.setCurrentItem(item)
                    break
            self.wait_for(lambda: dialog.view and dialog.view.selected == identifier and not dialog.busy)
            self.assertIn('仅分析留存材料', dialog.status.text())
            self.assertFalse(requests)
            dialog.composer.setPlainText('请解释当时的串口记录')
            self.assertTrue(dialog.send_button.isEnabled())
            dialog.send_button.click()
            self.wait_for(lambda: '结合当时日志核对' in dialog.transcript.toPlainText() and not dialog.view.running)
            self.assertIn('已留存链路中断', str(requests[0]))
            output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if output:
                self.assertTrue(dialog.grab().save(str(Path(output) / 'archived-device-chat.png')))

    def test_qt_ai_report_dialog_follows_up_on_retained_material(self):
        from dataclasses import asdict
        from functools import partial
        from src.core.ai_client import DiagnosticModelClient
        from src.models.ai_diagnostics import DiagnosticTarget, ModelReply, ProviderProfile
        from src.services.ai_case_store import open_shared_cases
        from src.services.ai_diagnostic_service import AiDiagnosticService

        requests = []
        cancelled = threading.Event()

        class Client(DiagnosticModelClient):
            def complete_stream(self, history, tools, stop, on_text=None):
                requests.append((history, tuple(tools)))
                if len(requests) > 1:
                    on_text('后续请求正在生成')
                    if stop.wait(6):
                        cancelled.set()
                    raise InterruptedError('停止模拟回复')
                reply = '留存报告只表明第 24 轮连通性检查超时，原因仍待核实。'
                return ModelReply(reply, [], history + [dict(role='assistant', content=reply)])

        chat = self.controller.ai_chat
        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-analysis'), \
                patch('src.services.ai_case_store.open_shared_cases',
                      side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'analysis-case-fixture')), \
                patch('src.services.qt_ai_chat.AiDiagnosticService', side_effect=partial(AiDiagnosticService, client_factory=Client)):
            self.controller.submit('create', self.root / 'report-analysis', '历史报告分析项目')
            self.wait_for(lambda: len(self.window.projects) == 1 and self.window.ai_chat_action.isEnabled())
            identifier = self.window.selected_project
            workspace = self.controller.adapter._service
            workspace.models.save_profile(ProviderProfile(model='history-fixture', context_tokens=65536), 'synthetic-analysis-key')
            self.window.ai_chat_action.trigger()
            self.wait_for(lambda: identifier in chat.windows and not chat.windows[identifier].busy)
            store = self.controller.adapter._model_settings.stores[identifier]
            target = DiagnosticTarget(7, 'vlan107', 'COM7', '192.0.2.10', '192.0.2.1')
            store.save_report('analysis-fixture', dict(question='第 24 轮连通性超时', report='留存证据：第 24 轮连通性检查超时。',
                              channel=7, target=asdict(target), run_id='sample-run'))
            dialog = chat.windows[identifier]
            dialog.reports_button.click()
            self.wait_for(lambda: identifier in chat.report_windows and chat.report_windows[identifier].detail is not None)
            chat.report_windows[identifier].handoff_button.click()
            self.wait_for(lambda: dialog.view.history_analysis)
            self.assertIn('仅分析留存材料', dialog.status.text())
            self.assertNotIn('发送问题后按需采集', dialog.transcript.toPlainText())
            self.assertEqual(requests, [])
            dialog.composer.setPlainText('第 24 轮报告能确认什么？')
            self.assertTrue(dialog.send_button.isEnabled())
            dialog.send_button.click()
            self.wait_for(lambda: '原因仍待核实' in dialog.transcript.toPlainText() and not dialog.view.running)
            self.assertIn('留存证据', str(requests[0][0]))
            self.assertEqual(requests[0][1], ())
            output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if output:
                self.assertTrue(dialog.grab().save(str(Path(output) / 'ai-report-analysis.png')))
            dialog.composer.setPlainText('补充一个问题')
            dialog.send_button.click()
            self.wait_for(lambda: dialog.stop_button.isEnabled() and '后续请求正在生成' in dialog.transcript.toPlainText())
            dialog.stop_button.click()
            self.wait_for(lambda: cancelled.is_set() and not dialog.view.running)
            self.assertIn('原因仍待核实', dialog.transcript.toPlainText())

    def test_qt_ai_case_confirmation_keeps_source_and_shared_revision(self):
        from PySide6.QtWidgets import QMessageBox
        from src.services.ai_case_store import open_shared_cases

        chat = self.controller.ai_chat
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-cases'), \
                patch('src.services.ai_case_store.open_shared_cases',
                      side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'shared-cases')):
            self.controller.submit('create', self.root / 'case-a', '案例项目 A')
            self.wait_for(lambda: len(self.window.projects) == 1 and self.window.ai_chat_action.isEnabled())
            first = self.window.selected_project
            self.window.ai_chat_action.trigger()
            self.wait_for(lambda: first in chat.windows and not chat.windows[first].busy)
            store = self.controller.adapter._model_settings.stores[first]
            store.save_report('fixture-source', {'report': '合成模型推测，未经人工核实'})
            chat.windows[first].reports_button.click()
            self.wait_for(lambda: first in chat.report_windows and chat.report_windows[first].detail is not None)

            self.controller.submit('create', self.root / 'case-b', '案例项目 B')
            self.wait_for(lambda: len(self.window.projects) == 2 and self.window.selected_project != first)
            second = self.window.selected_project
            self.window.ai_chat_action.trigger()
            self.wait_for(lambda: second in chat.windows and not chat.windows[second].busy)
            chat.windows[second].cases_button.click()
            self.wait_for(lambda: second in chat.case_windows and not chat.case_windows[second].busy)
            other = chat.case_windows[second]
            self.assertEqual(other.cases.count(), 0)

            chat.report_windows[first].case_action.trigger()
            self.wait_for(lambda: first in chat.case_windows and chat.case_windows[first].report_id == 'fixture-source')
            dialog = chat.case_windows[first]
            self.assertEqual(dialog.project_id, first)
            self.assertEqual(dialog._values(), ('',) * 5)
            self.assertLessEqual(dialog.height(), dialog.screen().availableGeometry().height())
            case = ('通道 3 连通性样例', '验证机使用了错误的出站网卡', '换回已保存的通道网卡',
                    '合成复测通过', '样例设备 V1')
            for field, value in zip(dialog.fields, case):
                field.setText(value)
            with patch.object(QMessageBox, 'question', return_value=no) as confirm:
                dialog.save_button.click()
                self.assertEqual(confirm.call_args.args[-1], no)
                self.assertIn('各项目', confirm.call_args.args[2])
            self.assertEqual(store.cases(), [])
            self.assertEqual(dialog._values(), case)
            with patch.object(QMessageBox, 'question', return_value=yes):
                dialog.save_button.click()
                self.wait_for(lambda: dialog.row is not None and not dialog.busy)
            self.assertEqual(dialog.row.report_id, 'fixture-source')
            other.refresh_button.click()
            self.wait_for(lambda: other.cases.count() == 1 and not other.busy)
            other.cases.setCurrentRow(0)
            self.assertEqual(other.row, dialog.row)
            prior = dialog.row.version
            other.fields[-1].setText('B 未保存修改')
            dialog.fields[-1].setText('样例设备 V2')
            with patch.object(QMessageBox, 'question', return_value=yes):
                dialog.save_button.click()
                self.wait_for(lambda: dialog.row.version > prior and not dialog.busy)
                other.save_button.click()
                self.wait_for(lambda: '已被其它项目修改' in other.feedback.text())
            self.assertEqual(other.fields[-1].text(), 'B 未保存修改')

            dialog.toggle_button.click()
            self.wait_for(lambda: not dialog.busy and not dialog.row.active)
            self.assertEqual(store.cases(), [])
            with patch.object(QMessageBox, 'question', return_value=no) as confirm:
                self.controller.close_project()
                self.assertEqual(confirm.call_args.args[1], '放弃未保存的修改')
            self.assertIn(second, chat.case_windows)
            self.assertEqual(other.fields[-1].text(), 'B 未保存修改')
            output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if output:
                self.assertTrue(dialog.grab().save(str(Path(output) / 'ai-confirmed-cases.png')))
            with patch.object(QMessageBox, 'question', return_value=no) as confirm:
                dialog.delete_button.click()
                self.assertEqual(confirm.call_args.args[-1], no)
            self.assertEqual(len(store.cases(include_inactive=True)), 1)
            with patch.object(QMessageBox, 'question', return_value=yes):
                dialog.delete_button.click()
                self.wait_for(lambda: dialog.cases.count() == 0 and dialog.row is None)
            self.assertTrue(store.report('fixture-source'))
            self.controller.submit('close', first)
            self.wait_for(lambda: first not in chat.case_windows and second in chat.case_windows and len(self.window.projects) == 1)

    def test_qt_model_settings_use_shared_store_and_original_client(self):
        from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox
        from src.services.ai_case_store import open_shared_cases

        class Client:
            calls = []

            def __init__(self, profile, key, redactor, emit=None):
                self.profile = profile
                self.key = key

            def model_details(self, stop):
                self.calls.append(('models', self.profile.source_ip, self.key))
                return [{'id': 'fixture-model', 'context_tokens': 40960}]

            def test_connection(self, stop):
                self.calls.append(('test', self.profile.source_ip, self.key))
                return '支持工具调用', '模拟验证通过'

            def close(self):
                pass

        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-ai'), \
                patch('src.services.ai_case_store.open_shared_cases',
                   side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'case-fixture')), \
                patch('src.services.qt_model_settings.DiagnosticModelClient', Client), \
                patch('src.services.qt_model_settings.list_source_ips', return_value=(
                    dict(name='模拟网卡', ip='192.0.2.25', available=True),)), \
                patch('src.services.qt_model_settings.require_source_ip', side_effect=lambda ip: ip):
            self.controller.submit('create', self.root / 'qt-model-a', '模型配置项目 A')
            self.wait_for(lambda: len(self.window.projects) == 1 and self.window.model_settings_action.isEnabled())
            first = self.window.selected_project
            self.window.detail.tabs.setCurrentIndex(7)
            controller = self.controller.model_settings
            self.wait_for(lambda: first in controller.windows and not controller.windows[first].busy)
            form = controller.windows[first]
            self.assertTrue(form.draft)
            self.assertEqual(form.key.echoMode(), QLineEdit.EchoMode.Password)
            form.fields['name'].setText('模拟模型配置')
            form.model.setCurrentText('fixture-model')
            form.key.setText('synthetic-model-key')
            with patch.object(QInputDialog, 'getItem', return_value=('模拟网卡 | 192.0.2.25', True)):
                QTest.mouseClick(form.source, Qt.MouseButton.LeftButton)
                self.wait_for(lambda: form.source_ip == '192.0.2.25')
            self.assertFalse(self.controller.adapter._service.models.profiles())

            QTest.mouseClick(form.refresh_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not form.busy and form.model.findText('fixture-model') >= 0)
            self.assertIn('40960', form.capacity.text())
            self.assertEqual(form.key.text(), '')
            QTest.mouseClick(form.test_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not form.busy and '模拟验证通过' in form.feedback.text())
            self.assertEqual(Client.calls, [('models', '192.0.2.25', 'synthetic-model-key'),
                                           ('test', '192.0.2.25', 'synthetic-model-key')])
            saved = form.base
            self.assertTrue(saved.tested_fingerprint)
            output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if output:
                self.assertTrue(form.grab().save(str(Path(output) / 'ai-model-settings.png')))
            form.copy_action.trigger()
            self.assertTrue(form.draft)
            self.assertNotEqual(form.base.id, saved.id)
            self.assertEqual(form.source_ip, saved.source_ip)
            self.assertEqual(form.key.text(), '')
            QTest.mouseClick(form.save_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not form.busy and len(form.view.profiles) == 2)
            with self.assertRaisesRegex(ValueError, '尚未配置密钥'):
                self.controller.adapter._service.models.key(form.base)
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as confirm:
                form.delete_action.trigger()
                self.assertEqual(confirm.call_args.args[-1], QMessageBox.StandardButton.No)
            self.assertEqual(len(form.view.profiles), 2)

            self.controller.submit('create', self.root / 'qt-model-b', '模型配置项目 B')
            self.wait_for(lambda: len(self.window.projects) == 2 and self.window.selected_project != first)
            second = self.window.selected_project
            self.window.model_settings_action.trigger()
            self.wait_for(lambda: second in controller.windows and not controller.windows[second].busy)
            second_form = controller.windows[second]
            self.assertEqual(len(second_form.view.profiles), 2)
            self.assertEqual(second_form.base.id, saved.id)
            self.assertNotEqual(form.base.id, second_form.base.id)
            self.assertNotIn('synthetic-model-key', self.window.logs.text.toPlainText())

    def test_qt_unknown_task_review_requires_local_confirmation_and_preserves_verdict(self):
        from PySide6.QtWidgets import QMessageBox

        self.controller.unknown_task_action.trigger()
        self.wait_for(lambda: self.controller.unknown_task_dialog is not None)
        dialog = self.controller.unknown_task_dialog
        self.assertEqual(dialog.selection.count(), 1)
        self.assertFalse(dialog.review_button.isEnabled())
        QTest.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: self.controller.unknown_task_dialog is None)

        self.controller.submit('create', self.root / 'review', '旧任务核实项目')
        self.wait_for(lambda: len(self.window.projects) == 1)
        identifier = self.window.projects[0].project_id
        service = self.controller.adapter._service
        context = service.projects.opened[identifier]
        owner = f'gui:{identifier}:simulated-review'
        snapshot = service.projects.snapshot(context)
        service.status.begin(context, owner, snapshot, '_on_start')
        service.status.complete(owner, state='unknown')
        service.resources.acquire(owner, identifier, context.identity.name, ('serial:qt-native-review-fixture',))
        service.resources.release(owner, uncertain=True)
        self.controller.submit('refresh')
        self.wait_for(lambda: self.window.projects[0].state == 'unknown')
        self.assertFalse(self.window.detail.start_button.isEnabled())
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            self.assertTrue(self.window.grab().save(str(Path(output) / 'unknown-task-before-review.png')))
        self.controller.unknown_task_action.trigger()
        self.wait_for(lambda: self.controller.unknown_task_dialog is not None)
        dialog = self.controller.unknown_task_dialog
        dialog.selection.setCurrentIndex(1)
        self.assertEqual(dialog.owner.text(), owner)
        self.assertFalse(dialog.review_button.isEnabled())
        dialog.evidence.setPlainText('已核对模拟任务记录')
        self.assertTrue(dialog.review_button.isEnabled())

        if output:
            self.assertTrue(dialog.grab().save(str(Path(output) / 'unknown-task-review.png')))
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as confirm:
            QTest.mouseClick(dialog.review_button, Qt.MouseButton.LeftButton)
            self.assertEqual(confirm.call_args.args[-1], QMessageBox.StandardButton.No)
            self.assertIn(owner, confirm.call_args.args[2])
        self.assertFalse((service.directory / 'reconciliations').exists())
        self.assertIn(owner, service.resources.unknown_for(identifier))
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
                patch('serial.Serial', side_effect=AssertionError('review must never start hardware')):
            QTest.mouseClick(dialog.review_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: self.controller.unknown_task_dialog is None)
        self.assertTrue(self.window.detail.start_button.isEnabled())
        self.assertEqual(self.window.projects[0].active_task_count, 0)
        ledger = json.loads((snapshot / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual(ledger['state'], 'unknown')
        self.assertTrue(ledger['reconciled'])
        self.assertFalse(service.resources.unknown_for(identifier))
        self.assertNotIn('已核对模拟任务记录', self.window.logs.text.toPlainText())
        if output:
            self.assertTrue(self.window.grab().save(str(Path(output) / 'unknown-task-after-review.png')))

    def test_qt_system_health_shows_live_observations_and_collapses(self):
        self.controller.submit('create', self.root / 'health-project', '系统状态验证项目')
        self.wait_for(lambda: len(self.window.projects) == 1)
        project = self.window.projects[0]
        self.window.show_dashboard()
        panel = self.window.dashboard.system_health
        self.wait_for(lambda: '回调间隔' in panel.values[0].text() and '最近写入成功' in panel.values[2].text())
        self.assertIn('暂无任务日志', panel.values[3].text())
        self.assertIn('暂无手动枚举记录', panel.values[5].text())
        self.wait_for(lambda: '串口 / 电源 0' in panel.values[4].text())

        adapter = self.controller.adapter
        writer = adapter._log_writer
        self.assertTrue(writer.flush())
        baseline_failures = adapter.health_snapshot().log_write_failures
        target = LogView('09:10:11', 'INFO', project.project_id, project.name, '模拟任务进度', 'synthetic-job')
        failed_batches = []
        allow_recovery = threading.Event()
        write_text = writer._write_text

        def fail_target_batch(batch):
            if any(entry is target for _, entry in batch):
                failed_batches.append(len(batch))
                raise PermissionError('synthetic write denial')
            if failed_batches:
                # Keep the failure visible until the real native panel observes it.
                allow_recovery.wait(10)
            write_text(batch)

        with patch.object(writer, '_write_text', side_effect=fail_target_batch):
            try:
                adapter._record(target)
                self.wait_for(lambda: '最近写入失败' in panel.values[2].text())
            finally:
                allow_recovery.set()
        self.assertTrue(writer.flush())
        self.assertEqual(len(failed_batches), 1)
        expected_failures = baseline_failures + failed_batches[0]
        self.assertEqual(adapter.health_snapshot().log_write_failures, expected_failures)
        self.assertIn('需关注 0', panel.values[3].text())
        self.assertIn('最近收到任务日志', panel.values[3].text())
        self.window.resource_refresh_action.trigger()
        self.wait_for(lambda: '最近枚举完成' in panel.values[5].text() and '最近写入成功' in panel.values[2].text())
        self.assertTrue(panel.values[2].text().splitlines()[0].endswith(f'失败累计 {expected_failures}'),
                        panel.values[2].text())

        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        self.assertTrue(panel.scroll.isHidden())
        self.assertIn('串口 / 电源 0', panel.resource_summary.text())
        for size, filename, columns in (((1366, 768), 'system-health-overview.png', 3),
                                        ((830, 580), 'system-health-compact.png', 2)):
            self.window.resize(*size)
            if columns == 2 and self.window.sidebar.isHidden():
                self.window.toggle_sidebar()
            self.wait_for(lambda: panel.columns == columns)
            self.assertTrue(panel.scroll.isHidden())
            if columns == 2 and output:
                self.assertTrue(self.window.grab().save(str(Path(output) / 'system-health-compact-folded.png')))
            QTest.mouseClick(panel.toggle, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: panel.scroll.isVisible() and all(
                value.heightForWidth(value.width()) <= value.height() for value in panel.values))
            if columns == 3:
                self.wait_for(lambda: panel.scroll.verticalScrollBar().maximum() == 0)
                cards = self.window.dashboard.cards
                index = cards.model().index(0, 0)
                self.wait_for(lambda: cards.viewport().rect().contains(
                    cards.visualRect(index).adjusted(1, 1, -GAP, -GAP)))
            if output:
                self.assertTrue(self.window.grab().save(str(Path(output) / filename)))
            for value in panel.values:
                self.assertTrue(panel.details.rect().contains(value.mapTo(panel.details, value.rect().bottomRight())))
                self.assertLessEqual(value.heightForWidth(value.width()), value.height(), f'{size}: {value.text()}')
            self.assertEqual(panel.scroll.horizontalScrollBar().maximum(), 0)
            last_item = panel.values[-1]
            panel.scroll.ensureWidgetVisible(last_item, 0, 0)
            viewport = panel.scroll.viewport()
            self.assertTrue(viewport.rect().contains(last_item.mapTo(viewport, last_item.rect().bottomRight())))
            if columns == 3:
                QTest.mouseClick(panel.toggle, Qt.MouseButton.LeftButton)

        expanded_height = panel.height()
        QTest.mouseClick(panel.toggle, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: panel.scroll.isHidden() and panel.height() < expanded_height)
        QTest.mouseClick(panel.toggle, Qt.MouseButton.LeftButton)
        self.wait_for(panel.scroll.isVisible)

    def test_qt_live_ai_log_is_summarized_and_archived_original_stays_readable(self):
        from concurrent.futures import ThreadPoolExecutor
        from PySide6.QtGui import QColor
        from src.ui.qt.theme import WARNING

        messages = (
            '[AI对话] 会话12345678收到问题，进入排查队列；其它会话继续',
            '[AI对话] 会话12345678模型请求成功',
            '[AI对话] 操作12345678结束：{"action_state":"unknown","stdout":"合成未核实原始输出"}',
            '[AI对话] 操作abcdef12结束：{"action_state":"failed","error":"合成可见失败"}',
            '[AI对话] 会话12345678本轮结束；恢复状态：无临时修改',
        )

        def write():
            for message in messages:
                self.controller.adapter._record(LogView('09:10:11', 'INFO', '', '合成 AI', message))

        with ThreadPoolExecutor(max_workers=1) as worker:
            worker.submit(write).result(timeout=5)
        panel = self.window.logs
        self.wait_for(lambda: '本轮结束' in panel.text.toPlainText())
        visible = panel.text.toPlainText()
        self.assertIn('开始排查（已入队）', visible)
        self.assertIn('合成可见失败', visible)
        self.assertNotIn('模型请求成功', visible)
        self.assertNotIn('合成未核实原始输出', visible)
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            self.assertTrue(self.window.grab().save(str(Path(output) / 'ai-live-log-summary.png')))
        panel.level.setCurrentText('WARN')
        self.assertIn('结果待核实', panel.text.toPlainText())
        self.assertNotIn('本轮结束', panel.text.toPlainText())
        self.assertNotIn('合成可见失败', panel.text.toPlainText())
        self.app.processEvents()
        line = panel.text.document().findBlockByNumber(0)
        self.assertTrue(any(item.format.foreground().color() == QColor(WARNING) for item in line.layout().formats()))

        self.controller.archived_logs_action.trigger()
        self.wait_for(lambda: self.controller.archived_logs.dialog is not None)
        archive = self.controller.archived_logs.dialog
        self.wait_for(lambda: not archive.busy and '合成未核实原始输出' in archive.logs.text.toPlainText())
        archived = archive.logs.text.toPlainText()
        for message in messages:
            self.assertIn(message, archived)

    def test_qt_archived_logs_pages_original_workspace_and_serial_text_with_local_export(self):
        from PySide6.QtWidgets import QFileDialog

        path = self.root / 'archive-project'
        self.controller.submit('create', path, '归档项目')
        self.wait_for(lambda: len(self.window.projects) == 1)
        identifier = self.window.projects[0].project_id
        service = self.controller.adapter._service
        workspace_file = service.directory / 'workspace.log'
        with workspace_file.open('a', encoding='utf-8') as stream:
            stream.write('\n'.join(f'既有工作区原文-{index:03d}' for index in range(145)) + '\n')
        serial_directory = path / 'logs/serial'
        serial_directory.mkdir(parents=True)
        serial_file = serial_directory / 'vlan101_COM1_20261120.log'
        serial_file.write_text('2026-11-20_01:02:03 RX 启动原文\n2026-11-20_01:02:04 TX 发送原文\n', encoding='utf-8')
        original_serial = serial_file.read_bytes()

        self.controller.archived_logs_action.trigger()
        self.wait_for(lambda: self.controller.archived_logs.dialog is not None)
        dialog = self.controller.archived_logs.dialog
        self.wait_for(lambda: not dialog.busy and '原文-144' in dialog.logs.text.toPlainText())
        self.assertNotIn('原文-000', dialog.logs.text.toPlainText())
        self.assertNotIn('INFO', dialog.logs.text.toPlainText())
        self.assertTrue(dialog.older.isEnabled())
        QTest.mouseClick(dialog.older, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: not dialog.busy and '原文-000' in dialog.logs.text.toPlainText())
        dialog.source.setCurrentIndex(dialog.source.findData('serial'))
        self.wait_for(lambda: not dialog.busy and '启动原文' in dialog.logs.text.toPlainText())
        expected = '2026-11-20_01:02:03 RX 启动原文\n2026-11-20_01:02:04 TX 发送原文'
        self.assertEqual(dialog.logs.text.toPlainText(), expected)
        self.assertTrue(dialog.logs.level.isHidden())
        self.assertEqual(dialog.project_id, identifier)
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            directory = Path(output)
            directory.mkdir(parents=True, exist_ok=True)
            self.assertTrue(dialog.grab().save(str(directory / 'archived-serial-log.png')))
        dialog.logs.search.setText('启动')
        self.assertEqual(dialog.logs.text.toPlainText(), expected.splitlines()[0])
        exported = self.root / 'serial-filter.txt'
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(exported), '')):
            QTest.mouseClick(dialog.logs.export_button, Qt.MouseButton.LeftButton)
        self.wait_for(exported.is_file)
        contents = exported.read_text(encoding='utf-8-sig')
        self.assertIn(expected.splitlines()[0], contents)
        self.assertNotIn('发送原文', contents)
        self.assertEqual(serial_file.read_bytes(), original_serial)
        # A log can be rotated out of the directory while its newest page is open.
        with serial_file.open('a', encoding='utf-8') as stream:
            stream.writelines(f'archived line {n}\n' for n in range(180))
        dialog.latest.click()
        self.wait_for(lambda: not dialog.busy and dialog.older.isEnabled())
        serial_file.rename(serial_file.with_suffix('.rotated'))
        dialog.refresh_files.click()
        self.wait_for(lambda: not dialog.busy and dialog.files.count() == 0)
        self.assertIsNone(dialog.cursor)
        self.assertFalse(dialog.older.isEnabled())
        self.assertFalse(dialog.latest.isEnabled())
        self.assertEqual(dialog.logs.text.toPlainText(), '')
        if output:
            self.assertTrue(dialog.grab().save(str(Path(output) / 'archived-empty-after-refresh.png')))
        main_directory = path / 'logs/main'
        monitor_directory = main_directory / 'resource_monitor'
        monitor_directory.mkdir(parents=True)
        main_file = main_directory / 'line_check_20261120_113355.log'
        main_file.write_text('\n'.join(f'项目主原文-{i:03d}' for i in range(132)) + '\n', encoding='utf-8')
        (monitor_directory / 'transport_history_20261120_113355_000123.jsonl').write_text(
            '{"sample":"资源采样"}\n', encoding='utf-8')
        dialog.logs.search.clear()
        dialog.source.setCurrentIndex(dialog.source.findData('project'))
        self.wait_for(lambda: not dialog.busy and '资源采样' in dialog.logs.text.toPlainText())
        self.assertEqual(dialog.files.count(), 2)
        dialog.files.setCurrentIndex(1)
        self.wait_for(lambda: not dialog.busy and '项目主原文-131' in dialog.logs.text.toPlainText())
        self.assertNotIn('项目主原文-000', dialog.logs.text.toPlainText())
        dialog.older.click()
        self.wait_for(lambda: not dialog.busy and '项目主原文-000' in dialog.logs.text.toPlainText())
        self.assertNotIn('发送原文', dialog.logs.text.toPlainText())
        if output:
            self.assertTrue(dialog.grab().save(str(Path(output) / 'archived-project-main.png')))
        dialog.close()

    def test_qt_instance_pairing_issues_expires_and_confirms_selected_slot(self):
        from src.services.qt_workspace_adapter import ProjectCommandResult
        workspace = self.controller.adapter._service
        manager = workspace.management()
        def slot(number):
            return dict(slot=number, instance_id=f'fixture-{number}', paired=False, enabled=False,
                        name='', url='', vpn=False, channel_ids=[], capability_ids=[], scopes=[])
        with patch.object(manager, 'status', return_value={}), patch.object(manager, 'slot', side_effect=slot), \
                patch.object(manager, 'create_pairing', return_value='fixture-one-use'), \
                patch('src.services.remote_instance_management.read_startup', return_value=dict(mode='direct', slot=4)), \
                patch.object(manager, 'pair', return_value=dict(slot(5), paired=True, name='模拟实例')) as pair:
            self.controller.instance_status_action.trigger()
            parent = self.controller.instance_status_dialog
            self.wait_for(lambda: parent.request is None)
            parent.open_pairing()
            view = parent.pairing
            self.wait_for(lambda: view.loaded and view.loaded['slot'] == 4)
            view.generate.click()
            self.wait_for(lambda: view.copy.isEnabled())
            self.assertEqual(view.generated.text(), 'fixture-one-use')
            view.expires = time.monotonic() - 1
            view.sync_code()
            self.assertFalse(view.copy.isEnabled())
            self.assertEqual(view.generated.text(), '')
            view.slot.setValue(5)
            self.wait_for(lambda: view.loaded and view.loaded['slot'] == 5)
            view.url.setText('ws://127.0.0.1:18761')
            view.name.setText('模拟实例')
            view.secret.setText('fixture-one-use')
            with patch.object(parent, 'confirm', return_value=False):
                view.pair.click()
            pair.assert_not_called()
            with patch.object(parent, 'confirm', return_value=True):
                view.pair.click()
            self.wait_for(lambda: view.request is None)
            self.assertTrue(view.loaded['paired'])
            self.assertFalse(view.pair.isEnabled())
            self.assertEqual(view.secret.text(), '')
            pair.assert_called_once_with(5, 'ws://127.0.0.1:18761', '模拟实例', False, 'fixture-one-use')
            capture = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if capture:
                self.assertTrue(view.grab().save(str(Path(capture) / 'instance-pairing.png')))
            view.generate.click()
            old_request = view.request
            view.close()
            self.wait_for(lambda: self.controller.adapter._gateway_request is None)
            parent.open_pairing()
            reopened = parent.pairing
            reopened.show_result(ProjectCommandResult(old_request, 'gateway_pairing_code', payload=('obsolete', time.monotonic()+300)))
            self.assertEqual(reopened.generated.text(), '')
            self.wait_for(lambda: reopened.request is None)
            parent.close()

    def test_qt_instance_startup_save_requires_local_scope_and_survives_reopen(self):
        from src.services.remote_gateway_runtime import RemoteInstanceConfig
        from src.services.remote_instance_identity import RemoteInstanceIdentity
        from src.services.remote_instance_management import read_startup
        from test_ai_core import FakeCipher
        from test_remote_instance_management import SCOPES
        source = Path(__file__).resolve().parents[1]
        manager = self.controller.adapter._service.management()
        with patch.dict(os.environ, LOCALAPPDATA=str(self.root), LINECHECK_GATEWAY_SLOT='', LINECHECK_DISABLE_CAPABILITIES='0'), \
                patch.object(manager, 'app_dir', source), patch.object(manager, 'cipher', FakeCipher()), \
                patch.object(manager, 'start_gateway') as connect:
            identity = RemoteInstanceIdentity(manager.app_dir, slot=2)
            try:
                RemoteInstanceConfig(identity, manager.cipher).save(dict(instance_id=identity.instance_id,
                    credential='fixture-only', name='测试实例', url='ws://127.0.0.1:18761', vpn=False,
                    scopes=SCOPES, enabled=False, capability_ids=[], channel_ids=[]))
            finally:
                identity.close()
            self.controller.submit('create', self.root / 'startup-project', '本地项目')
            self.wait_for(lambda: bool(self.window.selected_project))
            self.controller.instance_status_action.trigger()
            parent = self.controller.instance_status_dialog
            self.wait_for(lambda: parent.request is None)
            action = next(a for a in parent.manage.menu().actions() if a.text() == '下次启动配置…')
            action.trigger()
            view = parent.startup_editor
            self.wait_for(lambda: bool(view.review))
            self.assertEqual(view.mode.currentData(), 'direct')
            view.mode.setCurrentIndex(1)
            self.assertFalse(view.save.isEnabled())
            view.slot.setValue(2)
            self.wait_for(lambda: view.review and view.review['slot']['slot'] == 2)
            self.assertIn('fake-user', view.identity.toPlainText())
            view.channels.item(15).setCheckState(Qt.CheckState.Checked)
            capability = next(view.capabilities.item(i) for i in range(view.capabilities.count())
                              if view.capabilities.item(i).data(Qt.ItemDataRole.UserRole) == 'firmware.upgrade')
            capability.setCheckState(Qt.CheckState.Checked)
            self.assertTrue(view.save.isEnabled())
            with patch.object(parent, 'confirm', return_value=False) as confirm:
                view.save.click()
                self.assertIn('通道：16', confirm.call_args.args[1])
            self.assertEqual(read_startup(manager.app_dir)['mode'], 'direct')
            with patch.object(parent, 'confirm', return_value=True):
                view.save.click()
                self.wait_for(lambda: parent.startup_editor is None)
            action.trigger()
            reopened = parent.startup_editor
            self.wait_for(lambda: bool(reopened.review))
            self.assertEqual(reopened.mode.currentData(), 'gateway')
            self.assertEqual(reopened.checked(reopened.channels), [16])
            self.assertEqual(reopened.checked(reopened.capabilities), ['firmware.upgrade'])
            self.assertIn('待重启', reopened.feedback.text())
            self._capture_serial(reopened, 'instance-startup.png')
            reopened.close()
            parent.close()
            connect.assert_not_called()

            previous = self.controller.adapter
            self.window.close()
            self.wait_for(lambda: previous.closed.is_set() and not self.window.isVisible())
            def connected(client):
                client.connected.set()
                client.stop.wait(20)
                client.connected.clear()

            with patch('src.services.remote_gateway_runtime.WindowsCredentialCipher', return_value=manager.cipher), \
                    patch('src.core.remote_gateway_transport.GatewayInstanceClient._network', connected):
                self.window = MainWindow(demo=False)
                self.controller = WorkspaceController(self.window, source, directory=self.root / 'workspace',
                                                      start_configured_gateway=True)
                self.window.show()
                self.wait_for(lambda: self.controller.ready)
                self.controller.open_project(self.root / 'startup-project')
                self.wait_for(lambda: bool(self.window.selected_project))
                self.wait_for(lambda: self.controller.adapter._service.gateway_runtime.client.connected.is_set())
                self.controller.instance_status_action.trigger()
                state = self.controller.instance_status_dialog
                self.wait_for(lambda: state.request is None)
                self.assertEqual(state.fields['current_mode'].text(), '统一接入')
                self.assertEqual(state.fields['current_slot'].text(), '2')
                self.assertEqual(state.fields['connected'].text(), '已连接')
                self._capture_serial(state, 'instance-client-restarted.png')
                state.close()
                self.window.close()
                self.wait_for(lambda: self.controller.adapter.closed.is_set())


    def test_qt_peer_status_shows_project_routing_and_its_instance(self):
        state = dict(current_mode='project_peers', gateway_state='未运行', current_slot=2,
                     instance_id='peer-test-id', run_id='peer-test-run', connected=False)
        management = self.controller.adapter._service.management()
        with patch.object(management, 'status', return_value=state):
            self.controller.instance_status_action.trigger()
            dialog = self.controller.instance_status_dialog
            self.wait_for(lambda: dialog.request is None)
            self.assertEqual(dialog.fields['current_mode'].text(), '按项目路由')
            self.assertEqual(dialog.fields['instance_id'].text(), 'peer-test-id')
            self.assertEqual(dialog.fields['connected'].text(), '不适用')
            dialog.close()

    def test_qt_instance_status_refresh_close_and_late_reply(self):
        from src.services.qt_workspace_adapter import ProjectCommandResult
        workspace = self.controller.adapter._service
        state = dict(current_mode='gateway', gateway_state='外部运行', current_slot=4,
                     instance_id='fixture-instance', run_id='fixture-run', connected=True)
        with patch.object(workspace, 'register_controller', side_effect=AssertionError('unexpected registration')), \
             patch.object(workspace.management(), 'status', side_effect=[
                 state, ValueError('读取失败'), dict(state, current_mode='direct', connected=False,
                                                instance_id='', run_id='', current_slot=None)]) as status:
            self.controller.instance_status_action.trigger()
            dialog = self.controller.instance_status_dialog
            first = dialog.request
            self.wait_for(lambda: dialog.request is None)
            self.assertEqual([field.text() for field in dialog.fields.values()],
                             ['统一接入', '外部运行', '4', 'fixture-instance', 'fixture-run', '已连接'])
            directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if directory:
                self.assertTrue(dialog.grab().save(str(Path(directory) / 'instance-status.png')))
            dialog.refresh_button.click()
            self.wait_for(lambda: dialog.request is None)
            self.assertTrue(all(field.text() == '—' for field in dialog.fields.values()))
            self.assertIn('读取失败', dialog.feedback.text())
            dialog.close()
            self.controller.instance_status_action.trigger()
            reopened = self.controller.instance_status_dialog
            reopened.show_result(ProjectCommandResult(first, 'instance_status', payload=state))
            self.assertEqual(reopened.fields['instance_id'].text(), '—')
            self.wait_for(lambda: reopened.request is None)
            self.assertEqual(reopened.fields['current_mode'].text(), '直接接入')
            self.assertEqual(reopened.fields['connected'].text(), '不适用')
            self.assertEqual(status.call_count, 3)
            management = workspace.management()
            rows = [dict(name='同名实例', instance_id=key, state='在线', seen=0) for key in ('id-a', 'id-b')]
            with patch.object(management.host, 'instances', return_value=rows), patch.object(management, 'revoke') as revoke:
                reopened.submit('gateway_instances')
                self.wait_for(lambda: reopened.request is None and reopened.instances.count() == 2)
                reopened.instances.setCurrentRow(1)
                reopened.sync_actions()
                self.assertTrue(reopened.revoke.isEnabled())
                with patch.object(reopened, 'confirm', return_value=False):
                    reopened.revoke.trigger()
                revoke.assert_not_called()
                with patch.object(reopened, 'confirm', return_value=True):
                    reopened.revoke.trigger()
                self.wait_for(lambda: reopened.request is None)
                revoke.assert_called_once_with('id-b')
            config = dict(host='127.0.0.1', port=18761, platforms=[], scopes=[])
            with patch.object(management, 'gateway_config', return_value=config), \
                    patch.object(management, 'save_gateway') as save:
                reopened.edit_gateway()
                self.wait_for(lambda: reopened.config_editor is not None)
                editor = reopened.config_editor
                editor.add_scope(dict(platform='feishu', robot='robot', corp='corp', chat_type='group',
                                      chat='chat-id', members=['*']))
                with patch.object(reopened, 'confirm', return_value=False):
                    editor.save()
                save.assert_not_called()
                editor.scopes.selectRow(0)
                editor.remove_scope()
                editor.port.setValue(18762)
                if directory:
                    self.assertTrue(editor.grab().save(str(Path(directory) / 'gateway-editor.png')))
                editor.save()
                self.wait_for(lambda: reopened.config_editor is None)
                self.assertEqual(save.call_args.args[0]['port'], 18762)
            reopened.close()

    def test_qt_remote_scope_confirm_binds_project_ids_and_cancel_preserves_grants(self):
        workspace = self.controller.adapter._service
        self.controller.submit('create', self.root / 'scope-a', '同名项目')
        self.wait_for(lambda: len(self.window.projects) == 1)
        first = self.window.selected_project
        self.controller.submit('create', self.root / 'scope-b', '同名项目')
        self.wait_for(lambda: len(self.window.projects) == 2)
        second = self.window.selected_project
        workspace.set_remote_projects([first])
        access = workspace.directory / 'remote_projects.json'
        original = access.read_bytes()
        with patch.object(workspace, 'set_remote_projects', side_effect=AssertionError('unexpected write')):
            self.controller.remote_scope_action.trigger()
            dialog = self.controller.remote_scope_dialog
            self.wait_for(lambda: dialog.table.rowCount() == 2)
            rows = {dialog.table.item(index, 1).text(): dialog.table.item(index, 2).text() for index in range(2)}
            self.assertEqual(rows, {first: '已授权', second: '未授权'})
            self.controller.submit('close', first)
            self.wait_for(lambda: len(self.window.projects) == 1)
            dialog.refresh_button.click()
            self.wait_for(lambda: dialog.request is None)
            names = {dialog.table.item(i, 1).text(): dialog.table.item(i, 0).text()
                     for i in range(dialog.table.rowCount())}
            self.assertEqual(names, {first: '未打开的项目', second: '同名项目'})
            directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if directory:
                self.assertTrue(dialog.grab().save(str(Path(directory) / 'remote-project-scope.png')))
        self.assertEqual(access.read_bytes(), original)
        from PySide6.QtWidgets import QMessageBox
        dialog.checks[second].setChecked(True)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel) as question:
            dialog.save_button.click()
            self.assertIn(first, question.call_args.args[2])
            self.assertIn(second, question.call_args.args[2])
            self.assertEqual(question.call_args.args[-1], QMessageBox.StandardButton.Cancel)
        self.assertEqual(access.read_bytes(), original)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            dialog.save_button.click()
            self.wait_for(lambda: not dialog.saving and dialog.feedback.text() == '已保存远程项目范围')
        self.assertEqual(workspace.remote_projects, {second})
        self.assertEqual(json.loads(access.read_text(encoding='utf-8')), [second])
        dialog.close()

    def test_qt_imported_connection_uses_confirmed_local_choice_without_connecting(self):
        from src.services.dingtalk_remote_store import RemoteConfigStore

        def open_dialog():
            self.controller.imported_connection_action.trigger()
            self.wait_for(lambda: self.controller._imported_connection_dialog is not None)
            return self.controller._imported_connection_dialog

        dialog = open_dialog()
        self.assertIn('暂无', dialog.candidates.currentText())
        self.assertFalse(dialog.apply_button.isEnabled())
        dialog.close()
        workspace = self.controller.adapter._service
        candidate_dir = workspace.directory / 'platforms/imported/0123456789abcdef0123'
        candidate = RemoteConfigStore(workspace.source_root, directory=candidate_dir)
        candidate.save(dict(client_id='incoming-fixture', client_secret='private-fixture-value', isolated=True))
        (candidate_dir / 'source.json').write_text(json.dumps({'name': '旧工作区验证'}), encoding='utf-8')
        existing = workspace.platform_config('dingtalk')
        existing.save(dict(client_id='previous-fixture'))
        original = existing.path.read_bytes()

        dialog = open_dialog()
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.candidates.itemText(1), '钉钉 · 旧工作区验证 · 01234567')
        dialog.candidates.setCurrentIndex(1)
        self.assertTrue(dialog.apply_button.isEnabled())
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            directory = Path(output)
            directory.mkdir(parents=True, exist_ok=True)
            self.assertTrue(dialog.grab().save(str(directory / 'imported-connection-choice.png')))
        QTest.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: self.controller._imported_connection_dialog is None)
        self.assertEqual(existing.path.read_bytes(), original)

        dialog = open_dialog()
        dialog.candidates.setCurrentIndex(1)
        with patch('socket.socket', side_effect=AssertionError('selecting config cannot connect')):
            QTest.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: self.controller._imported_connection_dialog is None)
        saved = existing.load()
        self.assertEqual(saved['client_id'], 'incoming-fixture')
        self.assertEqual(saved['client_secret'], 'private-fixture-value')
        self.assertFalse(saved['enabled'])
        self.assertIsNone(workspace.platforms['dingtalk'].transport)
        self.assertFalse(workspace.remote_projects)
        self.assertIn('钉钉接入配置已保存', self.window.statusBar().currentMessage())

    def test_qt_legacy_import_menu_uses_original_backup_and_selects_new_project(self):
        config = self.root / 'legacy' / 'config'
        config.mkdir(parents=True)
        source = config / 'test_project_config.ini'
        original = b'[project_info]\nproject_name = Legacy\n[telnet]\nrequest_url = http://192.0.2.200\n'
        source.write_bytes(original)
        destination = self.root / 'imported'
        with patch('PySide6.QtWidgets.QFileDialog.getExistingDirectory', side_effect=(str(config), str(destination))), \
             patch('PySide6.QtWidgets.QInputDialog.getText', return_value=('导入验证项目', True)), \
             patch('serial.Serial', side_effect=AssertionError('legacy import cannot open serial')):
            self.controller.import_action.trigger()
            self.wait_for(lambda: len(self.window.projects) == 1 and bool(self.window.selected_project))
        project = self.window.projects[0]
        self.assertEqual(project.name, '导入验证项目')
        self.assertEqual(project.project_id, self.window.selected_project)
        self.assertEqual(project.active_task_count, 0)
        self.assertEqual(source.read_bytes(), original)
        self.assertTrue((destination / 'project.linecheck.json').is_file())
        self.assertTrue(any('备份及SHA256校验完成' in entry.message for entry in self.window.logs.entries))
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            self.window.show_dashboard()
            self.app.processEvents()
            self.assertTrue(self.window.grab().save(str(Path(output)/'real-project-imported.png')))

    def test_close_waits_for_actual_worker_cleanup(self):
        self.controller.submit('create', self.root / 'closing', '关闭验证')
        self.wait_for(lambda: len(self.window.projects) == 1)
        workspace = self.controller.adapter._service
        project = self.window.projects[0].project_id
        stopping, finished = threading.Event(), threading.Event()

        class PlatformTransport:
            def begin_close(self):
                stopping.set()

            @property
            def idle(self):
                return finished.is_set()

        with patch.object(workspace.platforms['feishu'], 'transport', PlatformTransport()):
            try:
                self.window.close()
                self.wait_for(stopping.is_set)
                self.assertTrue(self.window.isVisible())
                self.assertIn(project, workspace.projects.opened)
                self.assertFalse(self.controller.adapter.closed.is_set())
                output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
                if output:
                    self.assertTrue(self.window.grab().save(str(Path(output)/'workspace-closing.png')))
            finally:
                finished.set()
            self.wait_for(lambda: self.controller.adapter.closed.is_set())
        self.assertFalse(workspace.projects.opened)
        self.wait_for(lambda: not self.window.isVisible())
        self.assertFalse(self.controller.adapter.thread.is_alive())

    def _configured_execution(self, numbers=(1, 7)):
        from qt_execution_fakes import ControlledPipeline, configure_project
        self.controller.submit('create', self.root / 'power-test', '模拟设备验证项目')
        self.wait_for(lambda: len(self.window.projects) == 1)
        project = self.window.projects[0]
        workspace = self.controller.adapter._service
        identities = configure_project(workspace, workspace.projects.opened[project.project_id], numbers=numbers)
        self.controller.submit('refresh')
        self.wait_for(lambda: f'已选 {len(numbers)}' in self.window.projects[0].channel_text)
        engine = ControlledPipeline()
        self.addCleanup(engine.release_stop.set)
        self.addCleanup(engine.finish.set)
        for item in (
            patch('src.core.network_adapter.read_adapter_identities', return_value=identities),
            patch('src.services.capability_device_services.PipelineOrchestrator', engine.factory),
            patch('serial.Serial', side_effect=AssertionError('physical hardware forbidden')),
        ):
            item.start()
            self.addCleanup(item.stop)
        return engine, project.project_id

    def test_qt_single_power_uses_selected_port_and_requires_local_confirmation(self):
        from functools import partial
        from PySide6.QtWidgets import QMessageBox
        from src.core.power_supply import channel_power_frame
        from src.services.power_on_service import turn_off_selected_channels
        from test_power_supply import FakeSerial

        pipeline, identifier = self._configured_execution()
        fake = FakeSerial()
        waits = []
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')

        def capture(widget, name):
            if output:
                Path(output).mkdir(parents=True, exist_ok=True)
                self.assertTrue(widget.grab().save(str(Path(output) / name)))

        def review(port, expected, answer):
            self.wait_for(lambda: self.window.detail.tabs.isTabEnabled(1))
            self.window.detail.tabs.setCurrentIndex(1)
            self.wait_for(lambda: self.controller._single_power_dialog is not None)
            dialog = self.controller._single_power_dialog
            self.assertEqual(dialog.project_id, identifier)
            self.assertEqual(dialog.port.currentData(), 'COM102')
            dialog.port.setCurrentIndex(dialog.port.findData(port))
            dialog.action.setCurrentIndex(dialog.action.findData('down'))
            self.assertTrue(dialog.rect().contains(dialog.review_button.geometry()))
            capture(dialog, 'single-power-selector.png' if port else 'single-power-manual.png')

            def confirm(parent, title, summary, buttons, default):
                self.assertEqual(title, '确认单次自动上/下电')
                for value in ('模拟设备验证项目', 'CH01、CH07', '下电', expected):
                    self.assertIn(value, summary)
                self.assertEqual(default, QMessageBox.StandardButton.No)
                return answer

            with patch('PySide6.QtWidgets.QMessageBox.question', side_effect=confirm) as question:
                QTest.mouseClick(dialog.review_button, Qt.MouseButton.LeftButton)
                self.wait_for(lambda: question.called)
            self.wait_for(lambda: self.controller._single_power_dialog is None)
            self.wait_for(lambda: not self.controller._preparing)

        ports = []

        def open_serial(**options):
            ports.append(options['port'])
            return fake

        with patch('src.services.qt_single_power.turn_off_selected_channels',
                   partial(turn_off_selected_channels, serial_factory=open_serial, sleep_fn=waits.append)):
            review('COM106', '程控电源：COM106', QMessageBox.StandardButton.No)
            self.assertFalse(self.window.projects[0].run_id)
            self.assertFalse(ports)
            review('COM106', '仅关闭所列通道', QMessageBox.StandardButton.Yes)
            self.wait_for(lambda: self.window.projects[0].state == 'completed' and self.window.projects[0].can_start)
            project = self.window.projects[0]
            self.assertEqual(project.test_type, '单次下电')
            self.assertEqual(project.configuration[0], ('本次电源操作', (('动作', '下电'), ('本次电源口', 'COM106'))))
            self.assertIn(('程控电源串口', 'COM102'), dict(project.configuration)['基础参数'])
            self.assertEqual(ports, ['COM106'])
            self.assertEqual(fake.writes, [channel_power_frame(channel, False) for channel in (1, 7)])
            self.assertEqual(waits, [1])
            capture(self.window, 'single-power-completion.png')
            review('', '无串口指令', QMessageBox.StandardButton.Yes)
            self.wait_for(lambda: self.window.projects[0].state_text == '已确认手动重启')
            self.assertEqual(ports, ['COM106'])
        self.assertFalse(pipeline.calls)

    def test_qt_parameter_window_real_preflight_cancel_and_safe_stop(self):
        from PySide6.QtWidgets import QLineEdit, QMessageBox
        from test_qt_parameter_writer import ParameterHarness, make_table
        _, identifier = self._configured_execution()
        harness = ParameterHarness()
        self.addCleanup(harness.release.set)
        table = make_table(self.root / 'synthetic-parameters.xlsx')
        self.window.detail.tabs.setCurrentIndex(3)
        windows = self.controller.parameter_writer.windows
        self.wait_for(lambda: identifier in windows)
        dialog = windows[identifier]
        execution = self.controller.adapter._executions[identifier]
        execution.capabilities.parameters.runner = harness.run
        self.assertFalse(dialog.clear.isChecked())
        self.assertFalse(dialog.exit_aging.isChecked())
        self.assertEqual(dialog.parallel.value(), 1)
        self.assertEqual(dialog.password.echoMode(), QLineEdit.EchoMode.Password)
        dialog.targets[1].setChecked(False)
        dialog.username.setText('fixture-parameter-user')
        dialog.password.setText('fixture-parameter-password')
        missing = self.root / 'missing-parameters.xlsx'
        with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName', return_value=(str(missing), '')):
            dialog._choose()
            self.wait_for(lambda: not dialog.busy and '文件不存在' in dialog.feedback.text())
        self.assertEqual(dialog.path.text(), '')
        with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName', return_value=(str(table), '')):
            dialog._choose()
            self.wait_for(lambda: not dialog.busy and '预检通过' in dialog.results.toPlainText())
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: not dialog.busy and dialog.write_button.isEnabled())
        directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        for name, size in (('wide', (760, 660)), ('small', (560, 430))):
            dialog.resize(*size)
            self.app.processEvents()
            self.assertTrue(dialog.write_button.isVisible())
            self.assertLess(dialog.close_button.geometry().right(), dialog.width())
            if directory:
                self.assertTrue(dialog.grab().save(str(Path(directory) / ('parameters-' + name + '.png'))))
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.No) as question:
            QTest.mouseClick(dialog.write_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not dialog.busy and question.called)
        self.assertIn('vlan107 / COM7', str(question.call_args))
        self.assertIn('读回校验全部 15 项', str(question.call_args))
        self.assertNotIn('fixture-parameter-password', str(question.call_args))
        self.assertFalse(harness.calls)
        harness.release.clear()
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.write_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: harness.entered.is_set() and not dialog.busy and dialog.stoppable)
            dialog.close()
            self.assertIs(windows[identifier], dialog)
            self.assertFalse(execution.idle)
            QTest.mouseClick(dialog.stop_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not dialog.busy and '清理' in dialog.feedback.text())
            self.assertFalse(execution.idle)
        harness.release.set()
        self.wait_for(lambda: '模拟工厂模式清理完成' in dialog.results.toPlainText())
        self.assertEqual([item.vlan for item in harness.calls[0][0]], ['vlan107'])
        if directory:
            self.assertTrue(dialog.grab().save(str(Path(directory) / 'parameters-stop-result.png')))
        dialog.close()
        self.wait_for(lambda: identifier not in windows)
        self.window.detail.tabs.setCurrentIndex(3)
        self.wait_for(lambda: identifier in windows)
        reopened = windows[identifier]
        self.assertEqual(reopened.path.text(), str(table))
        self.assertIn('模拟工厂模式清理完成', reopened.results.toPlainText())

    def test_qt_dut_and_parameter_writer_share_project_login_draft(self):
        from PySide6.QtWidgets import QLineEdit, QMessageBox
        from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettingsStore

        identifier, dut = self._open_dut_fixture()
        writers = self.controller.parameter_writer
        context = self.controller.adapter._service.projects.opened[identifier]
        path = context.config_dir / 'sample_upgrade_settings.ini'
        previous = path.read_bytes() if path.exists() else None

        def login(dialog):
            return dialog.username.text(), dialog.password.text()

        writers.open()
        self.wait_for(lambda: identifier in writers.windows and not writers.windows[identifier].busy)
        writer = writers.windows[identifier]
        self.assertEqual(login(writer), login(dut))
        self.assertEqual(writer.password.echoMode(), QLineEdit.EchoMode.Password)
        self.assertEqual(dut.password.echoMode(), QLineEdit.EchoMode.Password)
        writer.username.setText(' shared-fixture-user ')
        self.assertEqual(dut.username.text(), ' shared-fixture-user ')
        dut.password.setText('shared-fixture-password')
        self.assertEqual(writer.password.text(), 'shared-fixture-password')
        self.assertEqual(path.read_bytes() if path.exists() else None, previous)

        dut.targets[1]['selected'].setChecked(False)
        self.dut_harness.release.clear()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
                patch.object(QMessageBox, 'warning') as warning:
            dut.preview('query')
            self.assertTrue(writer.username.isReadOnly())
            self.assertTrue(writer.password.isReadOnly())
            self.wait_for(lambda: warning.called or dut.active and self.dut_harness.started.is_set())
            self.assertFalse(warning.called, dut.feedback.text())
            self.assertTrue(writer.username.isReadOnly())
        self.dut_harness.release.set()
        self.wait_for(lambda: not dut.active and 'TCP 23=可达' in dut.status.toPlainText())
        self.assertFalse(writer.username.isReadOnly())
        self.assertEqual([request.username for request in self.dut_harness.calls], ['shared-fixture-user'])
        self.assertEqual([request.password for request in self.dut_harness.calls], ['shared-fixture-password'])
        writer.password.setText('saved-fixture-password')
        self.assertEqual(dut.status.toPlainText(), '')

        with patch.object(SampleUpgradeSettingsStore, 'save', side_effect=OSError('synthetic write failure')):
            QTest.mouseClick(writer.save_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not writer.busy and '保存未完成' in writer.feedback.text())
        self.assertEqual(login(writer), login(dut))
        self.assertEqual(path.read_bytes() if path.exists() else None, previous)
        QTest.mouseClick(writer.save_button, Qt.MouseButton.LeftButton)
        self.assertTrue(dut.password.isReadOnly())
        self.wait_for(lambda: not writer.busy and '已保存' in writer.feedback.text())
        saved = ('shared-fixture-user', 'saved-fixture-password')
        self.assertEqual(login(writer), saved)
        self.assertEqual(login(dut), saved)
        data = SampleUpgradeSettingsStore(path).load()
        self.assertEqual((data.parameter_initial_username, data.parameter_initial_password), saved)
        self.assertNotIn(saved[1], self.window.logs.text.toPlainText())

        writer.password.setText('discard-fixture-password')
        dut.close()
        self.wait_for(lambda: identifier not in self.controller.dut_windows)
        self.controller.open_dut()
        self.wait_for(lambda: identifier in self.controller.dut_windows)
        dut = self.controller.dut_windows[identifier]
        self.assertEqual(login(dut), login(writer))
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard):
            writer.close()
            self.wait_for(lambda: identifier not in writers.windows)
        self.assertEqual(login(dut), saved)

        self.controller.submit('create', self.root / 'different-login', '独立凭据项目')
        self.wait_for(lambda: len(self.window.projects) == 2)
        other = next(project.project_id for project in self.window.projects if project.project_id != identifier)
        self.window.select_project(other)
        writers.open()
        self.wait_for(lambda: other in writers.windows and not writers.windows[other].busy)
        other_writer = writers.windows[other]
        self.assertNotEqual(login(other_writer), saved)
        other_writer.password.setText('other-project-password')
        self.assertEqual(login(dut), saved)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard):
            other_writer.close()
            self.wait_for(lambda: other not in writers.windows)

    def test_qt_full_upgrade_without_power_requires_manual_restart_acknowledgement(self):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QPushButton
        from line_check_assistant.config_store import ChannelConfigStore
        from test_qt_firmware_upgrade import UpgradeHarness
        _, identifier = self._configured_execution()
        workspace = self.controller.adapter._service
        context = workspace.projects.opened[identifier]
        store = ChannelConfigStore(context.config_dir / 'network_card_ip.ini')
        store.save(store.load(), '')
        workspace.projects.save(context)
        harness = UpgradeHarness()
        self.addCleanup(harness.finished.set)
        path = self.root / 'fixture-manual.bin'
        path.write_bytes(b'synthetic firmware for manual restart UI')
        handle = patch('src.services.qt_firmware_upgrade.inspect_upgrade_network', return_value=[])
        handle.start()
        self.addCleanup(handle.stop)
        self.controller.open_upgrade()
        self.wait_for(lambda: identifier in self.controller.upgrade_windows)
        dialog = self.controller.upgrade_windows[identifier]
        execution = self.controller.adapter._executions[identifier]
        execution.upgrade.observation.engine = harness.dispatch
        dialog.mode.setCurrentText('全包升级')
        dialog.transfer.setCurrentText('Tftp Put')
        dialog.firmware.setText(str(path))
        dialog.targets[1].setChecked(False)
        dialog.username.setText('fixture-upgrade-user')
        dialog.password.setText('fixture-upgrade-secret')
        dialog.save_button.click()
        self.wait_for(lambda: dialog.preview_button.isEnabled() and '已保存' in dialog.feedback.text())
        self.assertIn('手动重启', dialog.power_label.text())
        directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if directory:
            self.assertTrue(dialog.grab().save(str(Path(directory) / 'firmware-manual-ready.png')))

        def decide(top, accepted):
            self.assertEqual(top.windowTitle(), '确认样机手动重启')
            details = top.findChild(QPlainTextEdit)
            self.assertTrue(details.isReadOnly())
            for text in ('SHA256', 'CH07', 'COM7', '已重启，继续升级'):
                self.assertIn(text, details.toPlainText())
            self.assertNotIn('fixture-upgrade-secret', details.toPlainText())
            box = top.findChild(QDialogButtonBox)
            self.assertTrue(box.button(QDialogButtonBox.StandardButton.Cancel).isDefault())
            proceed = next(button for button in top.findChildren(QPushButton) if '继续升级' in button.text())
            self.assertFalse(proceed.autoDefault())
            if directory and not accepted:
                top.show()
                self.app.processEvents()
                self.assertTrue(top.grab().save(str(Path(directory) / 'firmware-manual-confirm.png')))
                top.close()
            return QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected

        with patch.object(QDialog, 'exec', new=lambda top: decide(top, False)):
            dialog.preview_button.click()
            self.wait_for(lambda: not dialog.busy and '已取消' in dialog.feedback.text())
        self.assertFalse(harness.calls)
        with patch.object(QDialog, 'exec', new=lambda top: decide(top, True)):
            dialog.preview_button.click()
            self.wait_for(lambda: not dialog.busy and '模拟引擎结果' in dialog.results.toPlainText())
        method, requests, _ = harness.calls[0]
        self.assertEqual(method, 'Tftp Put')
        self.assertEqual([r.power_serial_port for r in requests], [''])

    def test_qt_firmware_preview_cancel_and_safe_stop_survive_window_reopen(self):
        from PySide6.QtWidgets import QLineEdit, QMessageBox
        from test_qt_firmware_upgrade import UpgradeHarness
        _, identifier = self._configured_execution()
        harness = UpgradeHarness()
        self.addCleanup(harness.finished.set)
        handle = patch('src.services.qt_firmware_upgrade.inspect_upgrade_network', return_value=[])
        handle.start()
        self.addCleanup(handle.stop)
        path = self.root / 'fixture.bin'
        path.write_bytes(b'firmware for native GUI simulation')
        self.window.detail.tabs.setCurrentIndex(2)
        self.wait_for(lambda: identifier in self.controller.upgrade_windows)
        execution = self.controller.adapter._executions[identifier]
        execution.upgrade.observation.engine = harness.dispatch
        dialog = self.controller.upgrade_windows[identifier]
        dialog.firmware.setText(str(path))
        dialog.mode.setCurrentText('页面升级')
        dialog.targets[1].setChecked(False)
        dialog.username.setText('fixture-upgrade-user')
        dialog.password.setText('fixture-upgrade-secret')
        self.assertEqual(dialog.password.echoMode(), QLineEdit.EchoMode.Password)
        self.assertFalse(dialog.preview_button.isEnabled())
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: dialog.preview_button.isEnabled() and '已保存' in dialog.feedback.text())
        self.assertFalse(harness.calls)
        directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if directory:
            dialog.mode.setCurrentText('全包升级')
            self.app.processEvents()
            self.assertTrue(dialog.grab().save(str(Path(directory) / 'firmware-full.png')))
            dialog.mode.setCurrentText('页面升级')
        for name, size in (('wide', (780, 680)), ('small', (510, 440))):
            dialog.resize(*size)
            self.app.processEvents()
            self.assertTrue(dialog.preview_button.isVisible())
            self.assertLessEqual(dialog.close_button.geometry().right(), dialog.width())
            if directory:
                self.assertTrue(dialog.grab().save(str(Path(directory) / ('firmware-' + name + '.png'))))
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.No) as question:
            QTest.mouseClick(dialog.preview_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: question.called and not dialog.busy)
        self.assertIn('SHA256', str(question.call_args))
        self.assertIn('CH07', str(question.call_args))
        self.assertNotIn('fixture-upgrade-secret', str(question.call_args))
        self.assertFalse(harness.calls)
        harness.finished.clear()
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.preview_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: harness.entered.is_set() and not dialog.busy)
            dialog.close()
            self.wait_for(lambda: identifier not in self.controller.upgrade_windows)
            self.assertFalse(execution.idle)
            self.controller.open_upgrade()
            self.wait_for(lambda: identifier in self.controller.upgrade_windows)
            reopened = self.controller.upgrade_windows[identifier]
            self.assertEqual(reopened.username.text(), 'fixture-upgrade-user')
            self.assertTrue(reopened.stop_button.isEnabled())
            QTest.mouseClick(reopened.stop_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not reopened.busy and '停止' in reopened.feedback.text())
            self.assertFalse(execution.idle)
        harness.finished.set()
        self.wait_for(lambda: '模拟安全停止' in reopened.results.toPlainText())
        self.assertEqual(harness.calls[0][0], '页面升级')
        self.assertEqual([request.vlan for request in harness.calls[0][1]], ['vlan107'])

    def test_qt_full_upgrade_logs_are_readonly_and_close_with_engine(self):
        from PySide6.QtWidgets import QMessageBox
        from test_qt_firmware_upgrade import UpgradeHarness
        _, identifier = self._configured_execution()
        harness = UpgradeHarness()
        harness.finished.clear()
        self.addCleanup(harness.finished.set)
        handle = patch('src.services.qt_firmware_upgrade.inspect_upgrade_network', return_value=[])
        handle.start()
        self.addCleanup(handle.stop)
        path = self.root / 'fixture.bin'
        path.write_bytes(b'firmware for native GUI simulation')
        self.controller.open_serial()
        self.wait_for(lambda: identifier in self.controller.serial_windows)
        manual = self.controller.serial_windows[identifier]
        self.controller.open_upgrade()
        self.wait_for(lambda: identifier in self.controller.upgrade_windows)
        execution = self.controller.adapter._executions[identifier]
        execution.upgrade.observation.engine = harness.dispatch
        dialog = self.controller.upgrade_windows[identifier]
        dialog.mode.setCurrentText('全包升级')
        dialog.transfer.setCurrentText('Tftp Put')
        dialog.firmware.setText(str(path))
        dialog.targets[1].setChecked(False)
        dialog.username.setText('fixture-upgrade-user')
        dialog.password.setText('fixture-upgrade-secret')
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: dialog.preview_button.isEnabled() and '已保存' in dialog.feedback.text())
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.preview_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: identifier in self.controller.job_serial_windows)
        logs = self.controller.job_serial_windows[identifier]
        self.wait_for(lambda: '原升级串口模拟输出' in logs.views['vlan107'][1].toPlainText()
                      and '原引擎已开始' in dialog.results.toPlainText())
        output = logs.views['vlan107'][1]
        self.assertTrue(output.isReadOnly())
        self.assertNotIn('fixture-secret-hidden', output.toPlainText())
        directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if directory:
            self.assertTrue(logs.grab().save(str(Path(directory) / 'firmware-serial-observation.png')))
            self.assertTrue(dialog.grab().save(str(Path(directory) / 'firmware-live-target.png')))
        dialog.close()
        self.wait_for(lambda: identifier not in self.controller.upgrade_windows)
        self.assertIs(self.controller.job_serial_windows[identifier], logs)
        self.assertFalse(execution.idle)
        harness.finished.set()
        self.wait_for(lambda: execution.idle and identifier not in self.controller.job_serial_windows)
        self.assertIs(self.controller.serial_windows[identifier], manual)
        self.assertFalse(harness.sessions['vlan107'].subscribers)

    def test_qt_parameter_serial_observation_waits_for_stop_and_leaves_manual_terminal(self):
        from PySide6.QtWidgets import QMessageBox
        from test_qt_parameter_writer import ParameterSerialHarness, make_table, use_serial_fallback
        _, identifier = self._configured_execution()
        workspace = self.controller.adapter._service
        use_serial_fallback(workspace, workspace.projects.opened[identifier])
        harness = ParameterSerialHarness(self.root)
        harness.release.clear()
        self.addCleanup(harness.release.set)
        table = make_table(self.root / 'synthetic-serial-parameters.xlsx')
        self.controller.open_serial()
        self.wait_for(lambda: identifier in self.controller.serial_windows)
        manual = self.controller.serial_windows[identifier]
        self.window.detail.tabs.setCurrentIndex(3)
        self.wait_for(lambda: identifier in self.controller.parameter_writer.windows)
        dialog = self.controller.parameter_writer.windows[identifier]
        execution = self.controller.adapter._executions[identifier]
        execution.capabilities.parameters.runner = harness.run
        dialog.username.setText('fixture-parameter-user')
        dialog.password.setText('fixture-parameter-private')
        with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName', return_value=(str(table), '')):
            dialog._choose()
            self.wait_for(lambda: not dialog.busy and '预检通过' in dialog.results.toPlainText())
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: not dialog.busy and dialog.write_button.isEnabled())
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.write_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not dialog.busy and identifier in self.controller.job_serial_windows)
            monitor = self.controller.job_serial_windows[identifier]
            self.assertIn('写参串口日志', monitor.windowTitle())
            self.assertEqual(monitor.tabs.count(), 2)
            monitor.tabs.setCurrentWidget(monitor.views['vlan107'][0])
            output = monitor.views['vlan107'][1]
            self.wait_for(lambda: 'vlan107 原写参串口模拟输出' in output.toPlainText())
            self.assertTrue(output.isReadOnly())
            self.assertNotIn('fixture-hidden-serial-write', output.toPlainText())
            directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if directory:
                self.assertTrue(monitor.grab().save(str(Path(directory) / 'parameters-serial-observation.png')))
            QTest.mouseClick(dialog.stop_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not dialog.busy and '清理' in dialog.feedback.text())
            self.assertFalse(execution.idle)
            self.assertIs(self.controller.job_serial_windows[identifier], monitor)
        harness.release.set()
        self.wait_for(lambda: execution.idle and identifier not in self.controller.job_serial_windows)
        self.assertIs(self.controller.serial_windows[identifier], manual)
        self.assertTrue(all(not serial.subscribers for serial in harness.sessions.values()))

    def test_qt_onu_profiles_discovery_and_stop_from_project_details(self):
        from PySide6.QtWidgets import QLineEdit, QMessageBox
        from test_qt_onu_query import OnuHarness, configure_onu
        _, identifier = self._configured_execution()
        workspace = self.controller.adapter._service
        store = configure_onu(workspace, workspace.projects.opened[identifier])
        harness = OnuHarness()
        self.addCleanup(harness.finished.set)
        self.window.detail.tabs.setCurrentIndex(4)
        windows = self.controller.onu_query.windows
        self.wait_for(lambda: identifier in windows)
        dialog = windows[identifier]
        execution = self.controller.adapter._executions[identifier]
        execution.capabilities.onu.registration_factory = harness.factory
        self.assertEqual(dialog.family.currentText(), 'C300')
        self.assertEqual(dialog.inputs['olt_ip'].text(), '192.0.2.153')
        self.assertEqual(dialog.inputs['password'].echoMode(), QLineEdit.EchoMode.Password)
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.No) as confirm:
            QTest.mouseClick(dialog.buttons['unregistered'], Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not dialog.busy and confirm.called)
        self.assertIn('gpon-olt_1/2/1', str(confirm.call_args))
        self.assertNotIn('private', str(confirm.call_args))
        self.assertFalse(harness.calls)
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.buttons['unregistered'], Qt.MouseButton.LeftButton)
            self.wait_for(lambda: dialog.tables['unregistered'].rowCount() == 1 and not dialog.active)
        table = dialog.tables['unregistered']
        self.assertEqual(table.item(0, 2).text(), 'SD-41（配置模板）')
        self.assertEqual(table.item(0, 3).text(), 'GPON（根据接口推断）')
        directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if directory:
            self.assertTrue(dialog.grab().save(str(Path(directory) / 'onu-discovery-C300.png')))
        dialog.family.setCurrentText('C600')
        self.assertEqual(table.rowCount(), 0)
        self.assertEqual(dialog.inputs['olt_ip'].text(), '192.0.2.156')
        self.assertEqual(dialog.inputs['source_ip'].text(), '192.0.2.60')
        dialog.scope['pon'].setValue(6)
        self.assertFalse(dialog.buttons['unregistered'].isEnabled())
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: not dialog.busy and dialog.buttons['unregistered'].isEnabled())
        self.assertEqual(store.load().c600_pon, 6)
        self.assertEqual(store.load().c300_pon, 1)
        dialog.tabs.setCurrentIndex(2)
        dialog.resize(565, 455)
        self.app.processEvents()
        self.assertTrue(dialog.close_button.isVisible())
        self.assertLess(dialog.close_button.geometry().right(), dialog.width())
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.buttons['dba'], Qt.MouseButton.LeftButton)
            self.wait_for(lambda: dialog.tables['templates'].rowCount() == 1 and not dialog.active)
            self.assertIn('Fixture template（1G）', dialog.tables['templates'].item(0, 1).text())
            if directory:
                self.assertTrue(dialog.grab().save(str(Path(directory) / 'onu-templates-C600-small.png')))
            harness.entered.clear()
            harness.finished.clear()
            QTest.mouseClick(dialog.buttons['connection'], Qt.MouseButton.LeftButton)
            self.wait_for(lambda: harness.entered.is_set() and not dialog.busy and dialog.stoppable)
            dialog.close()
            self.assertIs(windows[identifier], dialog)
            QTest.mouseClick(dialog.stop_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: harness.stop_seen.is_set() and not dialog.busy)
            self.assertFalse(execution.idle)
        harness.finished.set()
        self.wait_for(lambda: execution.idle and not dialog.busy and not dialog.stoppable
                      and '已停止' in dialog.feedback.text())
        dialog.close()
        self.wait_for(lambda: identifier not in windows)
        self.controller.onu_query.open()
        self.wait_for(lambda: identifier in windows)
        reopened = windows[identifier]
        self.assertIsNot(reopened, dialog)
        self.assertEqual(reopened.family.currentText(), 'C600')
        self.assertEqual(reopened.scope['pon'].value(), 6)
        self.assertEqual(reopened.provision.fields['services'].toPlainText(), '1,171,170')
        self.assertEqual([call[0:2] for call in harness.calls],
                         [('unregistered', 'C300'), ('templates', 'C600'), ('connection', 'C600')])

    def test_qt_onu_batch_registration_uses_readonly_preview_and_confirmed_ids(self):
        from PySide6.QtWidgets import QMessageBox
        from test_qt_onu_query import RegistrationHarness, configure_registration
        _, identifier = self._configured_execution()
        workspace = self.controller.adapter._service
        configure_registration(workspace, workspace.projects.opened[identifier])
        harness = RegistrationHarness()
        self.addCleanup(harness.finished.set)
        self.window.detail.tabs.setCurrentIndex(4)
        windows = self.controller.onu_query.windows
        self.wait_for(lambda: identifier in windows)
        dialog = windows[identifier]
        execution = self.controller.adapter._executions[identifier]
        execution.capabilities.onu.registration_factory = harness.factory
        dialog.family.setCurrentText('C600')
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.buttons['unregistered'], Qt.MouseButton.LeftButton)
            self.wait_for(lambda: len(dialog.provision.targets) == 2 and not dialog.active)
        dialog.tabs.setCurrentWidget(dialog.provision)
        for (_, selected, number), value in zip(dialog.provision.targets, (3, 4)):
            selected.setChecked(True)
            number.setValue(value)
        directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if directory:
            self.assertTrue(dialog.grab().save(str(Path(directory) / 'onu-business-targets.png')))
        QTest.mouseClick(dialog.provision.preview_button, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: not dialog.busy and dialog.register_button.isEnabled())
        self.assertTrue(dialog.plan_text.isReadOnly())
        expected = dialog.plan_text.toPlainText()
        self.assertIn('FIXT00000001 · gpon_olt-1/1/5 · ONU ID 3', expected)
        self.assertIn('FIXT00000002 · gpon_olt-1/1/5 · ONU ID 4', expected)
        self.assertNotIn('fixture-c600-private', expected)
        self.assertEqual(dialog.tabs.tabText(dialog.tabs.currentIndex()), '确认执行')
        if directory:
            self.assertTrue(dialog.grab().save(str(Path(directory) / 'onu-readonly-preview.png')))
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.No) as answer:
            QTest.mouseClick(dialog.register_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not dialog.busy and answer.called)
        self.assertFalse(harness.registrations)
        dialog.tabs.setCurrentWidget(dialog.provision)
        QTest.mouseClick(dialog.provision.preview_button, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: not dialog.busy and dialog.register_button.isEnabled())
        dialog.tabs.setCurrentWidget(dialog.provision)
        dialog.provision.targets[1][2].setValue(8)
        self.assertFalse(dialog.register_button.isEnabled())
        dialog.provision.targets[1][2].setValue(4)
        QTest.mouseClick(dialog.provision.preview_button, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: not dialog.busy and dialog.register_button.isEnabled())
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.register_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not dialog.busy and not dialog.active and bool(harness.registrations))
        self.assertIn('模拟注册与回读完成', dialog.feedback.text())
        self.assertEqual([item.onu_id for item in harness.registrations[0][1]], [3, 4])
        self.assertFalse(dialog.register_button.isEnabled())
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Discard):
            dialog.close()
            self.wait_for(lambda: identifier not in windows)

    def test_qt_c300_cleanup_lookup_and_confirmation_reuse_original_retry(self):
        from PySide6.QtWidgets import QMessageBox
        from test_qt_onu_query import CleanupHarness, configure_registration
        _, identifier = self._configured_execution()
        workspace = self.controller.adapter._service
        configure_registration(workspace, workspace.projects.opened[identifier])
        harness = CleanupHarness()
        self.window.detail.tabs.setCurrentIndex(4)
        windows = self.controller.onu_query.windows
        self.wait_for(lambda: identifier in windows)
        dialog = windows[identifier]
        self.controller.adapter._executions[identifier].capabilities.onu.registration_factory = harness.factory
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')

        def confirm(parent, title, summary, choices, default):
            self.assertIs(parent, dialog)
            if title == '确认注册 ONU':
                self.assertEqual(default, no)
                self.assertIn('仅删除以下候选', summary)
                self.assertIn('GPON12345678', summary)
                self.assertIn('ONU ID 3', summary)
            return yes

        with patch.object(QMessageBox, 'question', side_effect=confirm), patch.object(QMessageBox, 'exec', return_value=no):
            dialog.buttons['unregistered'].click()
            self.wait_for(lambda: len(dialog.provision.targets) == 1 and not dialog.active and not dialog.busy)
            page = dialog.provision
            dialog.tabs.setCurrentWidget(page)
            page.fields['onu_type'].setCurrentText('SD-41')
            page.targets[0][1].setChecked(True)
            page.targets[0][2].setValue(3)
            self.assertFalse(page.allow_cleanup.isChecked())
            self.assertFalse(page.cleanup_row.isVisible())
            page.allow_cleanup.setChecked(True)
            self.assertTrue(page.cleanup_row.isVisible())
            self.assertFalse(page.preview_button.isEnabled())
            page.cleanup_lookup.click()
            self.wait_for(lambda: page.cleanup_candidates.count() == 2 and not dialog.active and not dialog.busy)
            self.assertFalse(page.preview_button.isEnabled())
            page.cleanup_candidates.setCurrentIndex(1)
            self.assertTrue(page.preview_button.isEnabled())
            if directory:
                self.assertTrue(dialog.grab().save(str(Path(directory) / 'onu-c300-cleanup-selection.png')))
            page.preview_button.click()
            self.wait_for(lambda: dialog.register_button.isEnabled() and not dialog.busy)
            self.assertIn('gpon-onu_1/2/1:8', dialog.plan_text.toPlainText())
            if directory:
                self.assertTrue(dialog.grab().save(str(Path(directory) / 'onu-c300-cleanup-preview.png')))
            dialog.register_button.click()
            self.wait_for(lambda: '暂不保存' in dialog.feedback.text() and not dialog.active and not dialog.busy)
        self.assertEqual(harness.session.commands.count('no onu 8'), 1)
        self.assertNotIn('write', harness.session.commands)
        dialog.close()
        self.wait_for(lambda: identifier not in windows)

    def test_qt_onu_save_keeps_c300_prompt_and_c600_explicit_option(self):
        from PySide6.QtWidgets import QMessageBox
        from test_qt_onu_query import SaveHarness, configure_registration
        _, identifier = self._configured_execution()
        workspace = self.controller.adapter._service
        configure_registration(workspace, workspace.projects.opened[identifier])
        harness = SaveHarness()
        self.addCleanup(harness.finished.set)
        self.addCleanup(harness.save_finished.set)
        self.window.detail.tabs.setCurrentIndex(4)
        windows = self.controller.onu_query.windows
        self.wait_for(lambda: identifier in windows)
        dialog = windows[identifier]
        self.controller.adapter._executions[identifier].capabilities.onu.registration_factory = harness.factory
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')

        def decline(top):
            self.assertEqual(top.windowTitle(), '保存 OLT 最新配置')
            self.assertEqual(top.defaultButton(), top.button(no))
            self.assertIn('整台 OLT', top.text())
            if directory:
                top.show()
                self.app.processEvents()
                self.assertTrue(top.grab().save(str(Path(directory) / 'onu-c300-save-confirm.png')))
                top.close()
            return no

        with patch.object(QMessageBox, 'exec', new=decline), patch.object(QMessageBox, 'question', return_value=yes):
            for family, count in (('C300', 1), ('C600', 2)):
                dialog.family.setCurrentText(family)
                dialog.tabs.setCurrentIndex(0)
                dialog.buttons['unregistered'].click()
                self.wait_for(lambda: len(dialog.provision.targets) == count and not dialog.active and not dialog.busy)
                dialog.tabs.setCurrentWidget(dialog.provision)
                option = dialog.provision.write_after_success
                self.assertEqual(option.isVisible(), family == 'C600')
                self.assertFalse(option.isChecked())
                dialog.provision.targets[0][1].setChecked(True)
                if family == 'C600':
                    option.setChecked(True)
                    if directory:
                        self.assertTrue(dialog.grab().save(str(Path(directory) / 'onu-c600-save-option.png')))
                dialog.provision.preview_button.click()
                self.wait_for(lambda: dialog.register_button.isEnabled() and not dialog.busy)
                self.assertIn('另行确认' if family == 'C300' else '独立会话执行 write', dialog.plan_text.toPlainText())
                dialog.register_button.click()
                expected = '暂不保存' if family == 'C300' else '已写入启动配置'
                self.wait_for(lambda: expected in dialog.feedback.text() and not dialog.active and not dialog.busy)
                self.assertEqual(len(harness.save_calls), int(family == 'C600'))
        if directory:
            self.assertTrue(dialog.grab().save(str(Path(directory) / 'onu-c600-save-result.png')))
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard):
            dialog.close()
            self.wait_for(lambda: identifier not in windows)

    def test_qt_onu_registered_delete_follows_confirmed_batch_and_shows_each_result(self):
        from PySide6.QtCore import QItemSelectionModel
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox, QPlainTextEdit
        from test_qt_onu_query import DeleteHarness, configure_onu
        _, identifier = self._configured_execution()
        workspace = self.controller.adapter._service
        configure_onu(workspace, workspace.projects.opened[identifier])
        harness = DeleteHarness()
        self.window.detail.tabs.setCurrentIndex(4)
        windows = self.controller.onu_query.windows
        self.wait_for(lambda: identifier in windows)
        dialog = windows[identifier]
        execution = self.controller.adapter._executions[identifier]
        execution.capabilities.onu.registration_factory = harness.factory
        dialog.tabs.setCurrentIndex(1)
        table = dialog.tables['registered']
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            dialog.buttons['registered'].click()
            self.wait_for(lambda: table.rowCount() == 2 and not dialog.busy and not dialog.active)
        selected = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        for row in (1, 0):
            table.selectionModel().select(table.model().index(row, 0), selected)
        self.assertTrue(dialog.delete_button.isEnabled())
        directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')

        def confirm(confirmation, decision):
            self.assertIn('确认删除', confirmation.windowTitle())
            listing = confirmation.findChild(QPlainTextEdit)
            self.assertTrue(listing.isReadOnly())
            self.assertIn('FIXT00000003', listing.toPlainText())
            self.assertIn('FIXT00000004', listing.toPlainText())
            box = confirmation.findChild(QDialogButtonBox)
            self.assertTrue(box.button(QDialogButtonBox.StandardButton.Cancel).isDefault())
            if directory and decision == QDialog.DialogCode.Accepted:
                confirmation.show()
                self.app.processEvents()
                self.assertTrue(confirmation.grab().save(str(Path(directory) / 'onu-delete-confirm.png')))
                confirmation.close()
            return decision

        with patch.object(QDialog, 'exec', new=lambda top: confirm(top, QDialog.DialogCode.Rejected)):
            dialog.delete_button.click()
            self.wait_for(lambda: '已取消' in dialog.feedback.text() and not dialog.busy)
        self.assertFalse(harness.deleted)
        with patch.object(QDialog, 'exec', new=lambda top: confirm(top, QDialog.DialogCode.Accepted)):
            dialog.delete_button.click()
            self.wait_for(lambda: '成功 2 台' in dialog.feedback.text() and not dialog.busy and not dialog.active)
        self.assertEqual([item.onu_id for item in harness.deleted], [3, 4])
        self.assertEqual(table.item(0, 2).text(), '成功')
        self.assertEqual(table.item(1, 2).text(), '成功')
        self.assertFalse(dialog.delete_button.isEnabled())
        if directory:
            self.assertTrue(dialog.grab().save(str(Path(directory) / 'onu-delete-results.png')))
        dialog.close()
        self.wait_for(lambda: identifier not in windows)

    def _open_dut_fixture(self):
        from qt_dut_fakes import DutHarness
        from qt_execution_fakes import configure_project
        self.dut_harness = DutHarness()
        self.controller.submit('create', self.root / 'dut-project', '模拟 DUT 配置验证项目')
        self.wait_for(lambda: len(self.window.projects) == 1)
        identifier = self.window.projects[0].project_id
        workspace = self.controller.adapter._service
        identities = configure_project(workspace, workspace.projects.opened[identifier])
        for name, effect in (
            ('src.core.network_adapter.read_adapter_identities', lambda: identities),
            ('src.services.qt_dut_configuration.run_dut_telnet_enable_batch', self.dut_harness.enable_batch),
            ('src.services.qt_dut_configuration.run_dut_status_query_batch', self.dut_harness.query_batch),
            ('serial.Serial', AssertionError('physical serial forbidden')),
            ('socket.create_connection', AssertionError('physical network forbidden')),
        ):
            handle = patch(name, side_effect=effect)
            handle.start()
            self.addCleanup(handle.stop)
        self.addCleanup(self.dut_harness.release.set)
        self.controller.submit('refresh')
        self.wait_for(lambda: '已选 2' in self.window.projects[0].channel_text)
        self.window.select_project(identifier)
        self.controller._sync_actions()
        QTest.mouseClick(self.window.detail.tabs, Qt.MouseButton.LeftButton,
            pos=self.window.detail.tabs.tabRect(6).center())
        self.wait_for(lambda: identifier in self.controller.dut_windows)
        dialog = self.controller.dut_windows[identifier]
        dialog.username.setText('fixture-user')
        dialog.password.setText('fixture-private-password')
        return identifier, dialog

    def _open_management_fixture(self):
        from qt_voice_tr069_fakes import ManagementHarness
        identifier, dialog = self._open_dut_fixture()
        self.management = ManagementHarness()
        for name, handler in (('run_dut_status_query_batch', self.management.query_batch),
                              ('run_dut_advanced_config_batch', self.management.configure_batch)):
            handle = patch('src.services.qt_dut_configuration.' + name, side_effect=handler)
            handle.start()
            self.addCleanup(handle.stop)
        self.addCleanup(self.management.release_inform.set)
        return identifier, dialog

    def _capture_management_layout(self, dialog, panel):
        directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        for scenario, width, height, columns in (('wide', 1000, 740, 2), ('small', 560, 460, 1)):
            dialog.resize(width, height)
            self.wait_for(lambda: panel.form.columns == columns and panel.height() >= panel.minimumSizeHint().height())
            dialog.page_scroll.verticalScrollBar().setValue(0)
            self.app.processEvents()
            self.assertEqual((dialog.width(), dialog.height()), (width, height))
            self.assertEqual(dialog.page_scroll.horizontalScrollBar().maximum(), 0)
            boxes = []
            for row in panel.form.rows:
                box = row['group'].geometry()
                self.assertTrue(row['group'].rect().contains(row['field'].geometry()))
                self.assertFalse(any(box.intersects(other) for other in boxes))
                boxes.append(box)
            if directory:
                self.assertTrue(dialog.grab().save(str(Path(directory)/f'dut-{panel.feature}-{scenario}.png')))
            if scenario == 'small':
                dialog.page_scroll.verticalScrollBar().setValue(dialog.page_scroll.verticalScrollBar().maximum())
                self.app.processEvents()
                viewport = dialog.page_scroll.viewport()
                self.assertTrue(viewport.rect().contains(dialog.status.mapTo(viewport, QPoint(0,dialog.status.height()-1))))
                if directory:
                    self.assertTrue(dialog.grab().save(str(Path(directory)/f'dut-{panel.feature}-small-status.png')))

    def test_qt_voice_preserves_queried_line_and_original_ordered_codec_write(self):
        from PySide6.QtWidgets import QMessageBox, QLineEdit
        identifier, dialog = self._open_management_fixture()
        dialog.tabs.setCurrentIndex(4)
        panel = dialog.voice_tr069_panels['voice']
        panel.inputs['line_index'].setText('2')
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.query_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: bool(panel.query_id) and not dialog.active and not dialog.busy)
        self.assertEqual(panel.line_index, '2')
        self.assertEqual(panel.inputs['sip_mode'].currentText(), 'IMSSIP')
        self.assertEqual(panel.inputs['sip_mode'].count(), 1)
        self.assertEqual([field.currentText() for field in panel.codecs], ['G.729'] * 5)
        self.assertEqual(panel.inputs['auth_password'].echoMode(), QLineEdit.EchoMode.Password)
        self.assertNotIn('fixture-quoted-voice', dialog.status.toPlainText())
        self.assertNotIn('fixture-quoted-voice', self.window.logs.text.toPlainText())
        self._capture_management_layout(dialog, panel)
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.No) as question:
            QTest.mouseClick(dialog.enable_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: question.called and not dialog.busy)
        self.assertFalse(any(c[0]=='set' for client in self.management.clients for c in client.calls))
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.enable_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: len(self.management.clients)==4 and not dialog.active and not dialog.busy)
        for client in self.management.clients[2:]:
            call = next(c for c in client.calls if c[0]=='call')
            self.assertEqual([c['value'] for c in call[4]['paths']], ['G.729'] * 5)
            self.assertTrue(any(c[0]=='set' and c[2].endswith('SIP.Client.2.') for c in client.calls))
        self.assertFalse(panel.query_id)
        dialog.close(); self.wait_for(lambda: identifier not in self.controller.dut_windows)

    def test_qt_tr069_capability_fields_keep_manual_action_separate_from_query(self):
        from PySide6.QtWidgets import QMessageBox, QLineEdit
        identifier, dialog = self._open_management_fixture()
        dialog.tabs.setCurrentIndex(5)
        panel = dialog.voice_tr069_panels['tr069']
        manual = panel.inputs['manual_inform']
        manual.setChecked(True)
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.query_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: bool(panel.query_id) and not dialog.active and not dialog.busy)
        self.assertFalse(manual.isEnabled())
        self.assertFalse(manual.isChecked())
        self.assertFalse(panel.inputs['certificate_enabled'].isEnabled())
        self.assertIn('周期 Inform：未报告', dialog.status.toPlainText())
        self.assertIn('间隔未报告', dialog.status.toPlainText())
        self.assertEqual(panel.inputs['acs_password'].echoMode(), QLineEdit.EchoMode.Password)
        self.assertNotIn('fixture-acs-query-private', self.window.logs.text.toPlainText())
        self._capture_management_layout(dialog, panel)
        dialog.targets[1]['selected'].setChecked(False)
        self.assertFalse(panel.query_id)
        self.assertTrue(manual.isEnabled())
        self.management.reported_fields['X_SDMC_ManualInformStage'] = '3_finish_inform'
        manual.setChecked(True)
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.query_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: bool(panel.query_id) and not dialog.active and not dialog.busy)
        self.assertTrue(manual.isEnabled())
        self.assertTrue(manual.isChecked())
        self.assertFalse(any(c[0]=='call' for client in self.management.clients for c in client.calls))
        dialog.tabs.setCurrentIndex(4)
        dialog.tabs.setCurrentIndex(5)
        self.assertTrue(manual.isChecked())
        dialog.close(); self.wait_for(lambda: identifier not in self.controller.dut_windows)

    def _open_wifi_fixture(self):
        from qt_wifi_fakes import WifiHarness
        identifier, dialog = self._open_dut_fixture()
        self.wifi_harness = WifiHarness()
        for target, handler in (
            ('src.services.qt_dut_configuration.run_dut_status_query_batch', self.wifi_harness.query_batch),
            ('src.services.qt_dut_configuration.run_dut_advanced_config_batch', self.wifi_harness.configure_batch)):
            handle = patch(target, side_effect=handler)
            handle.start(); self.addCleanup(handle.stop)
        self.addCleanup(self.wifi_harness.release.set)
        self.addCleanup(self.wifi_harness.release_settle.set)
        dialog.tabs.setCurrentIndex(2)
        self.app.processEvents()
        return identifier, dialog

    def test_qt_wifi_actual_caps_dual_sync_password_and_responsive_forms(self):
        from PySide6.QtWidgets import QMessageBox, QLineEdit, QComboBox
        identifier, dialog = self._open_wifi_fixture()
        directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        for feature, tab in (('wifi_2g', 2), ('wifi_5g', 3)):
            dialog.tabs.setCurrentIndex(tab)
            panel = dialog.wifi_panels[feature]
            self.assertTrue(panel.isVisible())
            with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
                    patch('PySide6.QtWidgets.QMessageBox.warning') as blocked:
                QTest.mouseClick(dialog.query_button, Qt.MouseButton.LeftButton)
                self.wait_for(lambda: blocked.called or bool(panel.query_id) and not dialog.active and not dialog.busy)
                self.assertFalse(blocked.called, str(blocked.call_args))
            self.assertEqual(panel.text('password'), 'password2g' if tab == 2 else 'password5g')
            self.assertEqual(panel.inputs['password'].echoMode(), QLineEdit.EchoMode.Password)
            self.assertNotIn(panel.text('password'), self.window.logs.text.toPlainText())
            self.assertNotIn(panel.text('password'), dialog.status.toPlainText())
            channels = [panel.inputs['channel'].itemText(i) for i in range(panel.inputs['channel'].count())]
            self.assertIn('6' if tab == 2 else '36', channels)
            self.assertNotIn('13' if tab == 2 else '165', channels)
            panel.inputs['dual_band_enabled'].setChecked(True)
            self.assertTrue(all(p.inputs['dual_band_enabled'].isChecked() for p in dialog.wifi_panels.values()))
            for title, width, height in (('wide', 1000, 740), ('small', 560, 460)):
                dialog.resize(width, height)
                expected_columns = 2 if title == 'wide' else 1
                # Resizing the scroll viewport and then reflowing its child
                # posts another layout request. Capture after both settle.
                self.wait_for(lambda: panel.form.columns == expected_columns
                    and panel.height() >= panel.minimumSizeHint().height())
                dialog.page_scroll.verticalScrollBar().setValue(0)
                self.app.processEvents()
                self.assertEqual((dialog.width(), dialog.height()), (width, height))
                self.assertEqual(dialog.page_scroll.horizontalScrollBar().maximum(), 0)
                boxes = []
                for row in panel.form.rows:
                    if row['visible']:
                        self.assertTrue(row['group'].rect().contains(row['field'].geometry()), 'WiFi row clips a field')
                        geometry = row['group'].geometry()
                        self.assertFalse(any(geometry.intersects(box) for box in boxes), 'WiFi rows overlap')
                        boxes.append(geometry)
                        field = row['field']
                        if isinstance(field, QComboBox):
                            self.assertTrue(field.rect().contains(field.lineEdit().geometry()), 'WiFi selector clips its text editor')
                if directory:
                    self.assertTrue(dialog.grab().save(str(Path(directory)/('dut-'+feature+'-'+title+'.png'))))
                if title == 'small':
                    dialog.page_scroll.verticalScrollBar().setValue(dialog.page_scroll.verticalScrollBar().maximum())
                    self.app.processEvents()
                    self.assertTrue(dialog.page_scroll.viewport().rect().contains(dialog.status.mapTo(
                        dialog.page_scroll.viewport(), QPoint(0, dialog.status.height()-1))))
                    if directory:
                        self.assertTrue(dialog.grab().save(str(Path(directory)/('dut-'+feature+'-small-status.png'))))
            panel.inputs['security_mode'].setCurrentText('None')
            self.assertFalse(panel.inputs['password'].isVisible())
            self.assertEqual(panel.text('password'), 'password2g' if tab == 2 else 'password5g')
            panel.inputs['security_mode'].setCurrentText('WPA2-Personal')
            panel.inputs['ssid_index'].setCurrentText('2')
            self.assertFalse(panel.query_id)
            self.controller._dut_submit(identifier, 'poll', dict(token=dialog.token))
            self.wait_for(lambda: not self.controller._dut_requests)
            self.assertFalse(panel.query_id)
            dialog.resize(1000, 740)
        self.assertFalse([e for e in self.wifi_harness.events if e[0] in ('apply', 'configure')])
        dialog.close(); self.wait_for(lambda: identifier not in self.controller.dut_windows)

    def test_qt_wifi_confirm_increment_switch_and_stop_preserve_unverified_state(self):
        from PySide6.QtWidgets import QMessageBox
        identifier, dialog = self._open_wifi_fixture()
        panel = dialog.wifi_panels['wifi_2g']
        panel.inputs['ssid'].setText('Gui_009')
        panel.inputs['ssid_increment'].setChecked(True)
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.No) as question:
            QTest.mouseClick(dialog.enable_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: question.called and not dialog.busy)
            self.assertFalse(self.wifi_harness.calls)
            self.assertNotIn(panel.text('password'), str(question.call_args))
        self.wifi_harness.release_settle.clear()
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.enable_button, Qt.MouseButton.LeftButton)
            self.wait_for(self.wifi_harness.settle_entered.is_set)
            self.wait_for(lambda: dialog.active and not dialog.busy)
        self.assertEqual(self.wifi_harness.shared, [True])
        self.assertEqual(self.wifi_harness.state('通道 1').ssids['Device.WiFi.SSID.11.']['SSID'], 'Gui_009')
        self.assertEqual(self.wifi_harness.state('通道 7').ssids['Device.WiFi.SSID.11.']['SSID'], 'Gui_010')
        self.window.show_dashboard()
        self.assertFalse(self.wifi_harness.stop_seen.is_set())
        QTest.mouseClick(dialog.stop_button, Qt.MouseButton.LeftButton)
        self.wait_for(self.wifi_harness.stop_seen.is_set)
        self.assertFalse(self.controller.adapter._executions[identifier].idle)
        self.wifi_harness.release_settle.set()
        self.wait_for(lambda: not dialog.active and not dialog.busy)
        self.assertFalse(any(e[0]=='verify' for e in self.wifi_harness.events))
        self.assertIn('已停止', dialog.feedback.text())
        execution = self.controller.adapter._executions[identifier]
        self.assertFalse(any(row.get('ok') for row in execution.dut.rows.values()))
        dialog.close(); self.wait_for(lambda: identifier not in self.controller.dut_windows)

    def _open_wan_fixture(self):
        from qt_dut_fakes import WanHarness
        identifier, dialog = self._open_dut_fixture()
        self.wan_harness = WanHarness()
        for target, side_effect in (
            ('src.services.qt_dut_configuration.run_dut_wan_query_batch', self.wan_harness.wan_query_batch),
            ('src.services.qt_dut_configuration.run_dut_advanced_config_batch', self.wan_harness.wan_configure_batch)):
            handle = patch(target, side_effect=side_effect)
            handle.start(); self.addCleanup(handle.stop)
        self.addCleanup(self.wan_harness.release.set)
        QTest.mouseClick(dialog.tabs, Qt.MouseButton.LeftButton, pos=dialog.tabs.tabRect(1).center())
        self.app.processEvents()
        self.assertTrue(dialog.wan.isVisible())
        return identifier, dialog

    def test_qt_wan_query_shared_details_rules_and_actual_modify_payload(self):
        from PySide6.QtWidgets import QMessageBox, QLineEdit
        from src.models.dut_config_models import DutWanSettings
        from dataclasses import fields
        identifier, dialog = self._open_wan_fixture()
        panel = dialog.wan
        self.assertEqual(set(panel.settings()), {f.name for f in fields(DutWanSettings)})
        self.assertEqual(panel.settings()['vlan_id'],'200')
        panel.inputs['access_type'].setCurrentText('PPPoE')
        self.assertEqual(panel.text('mtu'),'1492')
        panel.inputs['ip_protocol'].setCurrentText('IPv4+IPv6（双栈）')
        panel.inputs['access_type'].setCurrentText('IPoE')
        panel.inputs['ipv4_type'].setCurrentText('静态')
        self.assertEqual(panel.text('ipv6_type'),'静态')
        panel.inputs['mode'].setCurrentText('桥接')
        self.assertFalse(panel.inputs['ip_protocol'].isVisible())
        self.assertTrue(panel.lan[0].isChecked())
        panel.inputs['service_type'].setCurrentText('IPTV')
        self.assertTrue(panel.inputs['multicast_vlan_id'].isVisible())
        panel.inputs['operation'].setCurrentText('修改')
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.query_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: bool(panel.query_id) and not dialog.active and not dialog.busy)
        self.assertEqual(panel.text('connection_index'),'1_INTERNET')
        self.assertEqual(panel.text('mtu'),'1492')
        self.assertEqual(panel.port_bind(),'265')
        self.assertEqual(panel.inputs['pppoe_password'].text(),'fixture-ppp-private')
        self.assertEqual(panel.inputs['pppoe_password'].echoMode(),QLineEdit.EchoMode.Password)
        panel.lan[0].setChecked(False)
        self.assertEqual(panel.port_bind(),'264')
        directory=os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        for title,width,height in (('wide',1000,740),('small',560,460)):
            dialog.resize(width,height); self.app.processEvents()
            self.assertEqual((dialog.width(),dialog.height()),(width,height))
            self.assertEqual(panel.form.columns,2 if title=='wide' else 1)
            self.assertEqual(dialog.page_scroll.horizontalScrollBar().maximum(),0)
            for row in panel.form.rows:
                if row['visible']:
                    self.assertTrue(row['group'].rect().contains(row['field'].geometry()),
                        'WAN row clips field: ' + str(panel.form.rows.index(row)))
            if directory: self.assertTrue(dialog.grab().save(str(Path(directory)/('dut-wan-'+title+'.png'))))
            if title=='small':
                dialog.page_scroll.verticalScrollBar().setValue(dialog.page_scroll.verticalScrollBar().maximum())
                self.app.processEvents()
                self.assertTrue(dialog.page_scroll.viewport().rect().contains(dialog.status.mapTo(
                    dialog.page_scroll.viewport(),QPoint(0,dialog.status.height()-1))))
                if directory: self.assertTrue(dialog.grab().save(str(Path(directory)/'dut-wan-small-status.png')))
        dialog.resize(1000,740)
        self.app.processEvents()
        from src.services.dut_advanced_config_service import validate_wan_settings
        self.assertEqual(validate_wan_settings(DutWanSettings(**panel.settings())), ())
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.No) as question:
            QTest.mouseClick(dialog.enable_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: question.called and not dialog.busy)
            self.assertFalse(self.wan_harness.operations)
            self.assertNotIn('fixture-ppp-private',str(question.call_args))
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.enable_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: len(self.wan_harness.operations)==2 and not dialog.active and not dialog.busy)
        self.assertTrue(all(p['PortBind']==264 and p['Method']=='modify' for _,p in self.wan_harness.operations))
        self.assertNotIn('fixture-ppp-private',self.window.logs.text.toPlainText())
        self.assertFalse(panel.query_id)
        dialog.close(); self.wait_for(lambda: identifier not in self.controller.dut_windows)

    def test_qt_wan_different_details_invalidation_switch_and_safe_stop(self):
        from PySide6.QtWidgets import QMessageBox
        identifier,dialog=self._open_wan_fixture()
        panel=dialog.wan; self.wan_harness.different=True
        panel.inputs['vlan_id'].setText('777')
        panel.inputs['operation'].setCurrentText('删除')
        with patch('PySide6.QtWidgets.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.query_button,Qt.MouseButton.LeftButton)
            self.wait_for(lambda: bool(panel.query_id) and not dialog.active and not dialog.busy)
        self.assertEqual(panel.text('vlan_id'),'777')
        self.assertIn('不一致',panel.feedback.text())
        dialog.tabs.setCurrentIndex(0); dialog.tabs.setCurrentIndex(1)
        self.assertEqual(panel.text('connection_index'),'1_INTERNET')
        dialog.targets[1]['selected'].setChecked(False)
        self.assertFalse(panel.query_id)
        self.controller._dut_submit(identifier,'poll',dict(token=dialog.token))
        self.wait_for(lambda: not self.controller._dut_requests)
        self.assertFalse(panel.query_id)
        panel.inputs['operation'].setCurrentText('新增')
        panel.inputs['mode'].setCurrentText('桥接')
        self.wan_harness.release.clear(); self.wan_harness.started.clear()
        with patch('PySide6.QtWidgets.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.enable_button,Qt.MouseButton.LeftButton)
            self.wait_for(self.wan_harness.started.is_set)
            self.wait_for(lambda: dialog.active and not dialog.busy)
        self.window.show_dashboard()
        self.assertFalse(self.wan_harness.stop_seen.is_set())
        QTest.mouseClick(dialog.stop_button,Qt.MouseButton.LeftButton)
        self.wait_for(self.wan_harness.stop_seen.is_set)
        self.assertFalse(self.controller.adapter._executions[identifier].idle)
        self.wan_harness.release.set()
        self.wait_for(lambda: not dialog.active and not dialog.busy)
        self.assertFalse(self.wan_harness.operations)
        dialog.close(); self.wait_for(lambda: identifier not in self.controller.dut_windows)

    def test_qt_dut_confirmation_query_and_responsive_layout(self):
        from PySide6.QtWidgets import QMessageBox, QLineEdit
        identifier, dialog = self._open_dut_fixture()
        self.assertFalse(self.dut_harness.calls)
        self.assertEqual(dialog.password.echoMode(), QLineEdit.EchoMode.Password)
        QTest.mouseClick(dialog.show_password, Qt.MouseButton.LeftButton,
            pos=QPoint(8, dialog.show_password.height() // 2))
        self.assertEqual(dialog.password.echoMode(), QLineEdit.EchoMode.Normal)
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.No) as confirm:
            QTest.mouseClick(dialog.enable_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: confirm.called and not dialog.busy)
            self.assertFalse(self.dut_harness.calls)
            self.assertNotIn('fixture-private-password', str(confirm.call_args))
        dialog.targets[1]['selected'].setChecked(False)
        dialog.parallel.setValue(2)
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.query_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not dialog.busy and dialog.active or self.dut_harness.started.is_set())
            self.wait_for(lambda: 'TCP 23=可达' in dialog.status.toPlainText())
            self.wait_for(lambda: not dialog.active)
        self.assertEqual([r.channel for r in self.dut_harness.calls], ['通道 7'])
        self.assertEqual(self.dut_harness.workers, [2])
        self.assertNotIn('fixture-private-password', self.window.logs.text.toPlainText())
        directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        for title, width, height in (('wide', 1000, 740), ('small', 560, 460)):
            dialog.resize(width, height)
            self.app.processEvents()
            self.assertEqual(dialog.width(), width)
            self.assertEqual(dialog.height(), height)
            self.assertEqual(dialog.page_scroll.horizontalScrollBar().maximum(), 0)
            self.assertEqual(dialog.scroll.horizontalScrollBar().maximum(), 0)
            self.assertTrue(dialog.close_button.isVisible())
            self.assertLessEqual(dialog.close_button.mapTo(dialog, QPoint(0, dialog.close_button.height())).y(), dialog.height())
            self.assertLessEqual(dialog.enable_button.mapTo(dialog, QPoint(dialog.enable_button.width(), 0)).x(), dialog.width())
            if title == 'wide':
                self.assertTrue(dialog.scroll.viewport().rect().contains(
                    dialog.targets[7]['card'].mapTo(dialog.scroll.viewport(),
                        QPoint(0, dialog.targets[7]['card'].height() - 1))))
            if directory:
                self.assertTrue(dialog.grab().save(str(Path(directory) / ('dut-telnet-' + title + '.png'))))
            if title == 'small':
                dialog.page_scroll.verticalScrollBar().setValue(dialog.page_scroll.verticalScrollBar().maximum())
                self.app.processEvents()
                self.assertTrue(dialog.page_scroll.viewport().rect().contains(dialog.status.mapTo(
                    dialog.page_scroll.viewport(), QPoint(0, dialog.status.height() - 1))))
                if directory:
                    self.assertTrue(dialog.grab().save(str(Path(directory) / 'dut-telnet-small-status.png')))
        dialog.targets[1]['selected'].setChecked(True)
        self.assertFalse(dialog.status.toPlainText())
        self.controller._dut_submit(identifier, 'poll', dict(token=dialog.token))
        self.wait_for(lambda: not self.controller._dut_requests)
        self.assertFalse(dialog.status.toPlainText())
        dialog.close()
        self.wait_for(lambda: identifier not in self.controller.dut_windows)

    def test_qt_dut_close_switch_reopen_and_stop_wait_for_original_job(self):
        from PySide6.QtWidgets import QMessageBox
        identifier, dialog = self._open_dut_fixture()
        self.dut_harness.release.clear()
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.enable_button, Qt.MouseButton.LeftButton)
            self.wait_for(self.dut_harness.started.is_set)
            self.wait_for(lambda: dialog.active and not dialog.busy)
        job = self.controller.adapter._executions[identifier].dut.latest
        dialog.close()
        self.wait_for(lambda: identifier not in self.controller.dut_windows)
        self.assertFalse(self.dut_harness.stop_seen.is_set())
        self.controller.submit('create', self.root / 'second-project', '切换页面验证')
        self.wait_for(lambda: len(self.window.projects) == 2)
        self.assertFalse(self.dut_harness.stop_seen.is_set())
        self.window.select_project(identifier)
        self.controller.open_dut()
        self.wait_for(lambda: identifier in self.controller.dut_windows)
        dialog = self.controller.dut_windows[identifier]
        self.assertTrue(dialog.active)
        self.assertEqual(self.controller.adapter._executions[identifier].dut.latest, job)
        QTest.mouseClick(dialog.stop_button, Qt.MouseButton.LeftButton)
        self.wait_for(self.dut_harness.stop_seen.is_set)
        self.assertFalse(self.controller.adapter._executions[identifier].idle)
        self.assertTrue(self.controller.adapter._service.resources.owners)
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        self.wait_for(lambda: bool(heartbeat))
        self.dut_harness.release.set()
        self.wait_for(lambda: not dialog.active and '已停止' in dialog.feedback.text())
        self.assertEqual(len(self.dut_harness.calls), 1)
        dialog.close()
        self.wait_for(lambda: identifier not in self.controller.dut_windows)

    def _open_serial_fixture(self, ports=('COM216', 'COM222')):
        from qt_serial_fakes import SerialHarness
        from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
        self.serial_harness = SerialHarness().start()
        self.addCleanup(self.serial_harness.stop)
        self.controller.submit('create', self.root / 'serial-project', '模拟串口验证项目')
        self.wait_for(lambda: len(self.window.projects) == 1)
        project = self.window.projects[0]
        workspace = self.controller.adapter._service
        context = workspace.projects.opened[project.project_id]
        ChannelConfigStore(context.config_dir / 'network_card_ip.ini').save([
            ChannelConfig('channel_1', vlan_name='VLAN116', serial_port=ports[0]),
            ChannelConfig('channel_7', vlan_name='VLAN122', serial_port=ports[1])], '')
        workspace.projects.save(context)
        self.controller.submit('refresh')
        self.wait_for(lambda: '已选 2' in self.window.projects[0].channel_text)
        tab = self.window.detail.tabs.tabRect(5).center()
        QTest.mouseClick(self.window.detail.tabs, Qt.MouseButton.LeftButton, pos=tab)
        self.wait_for(lambda: project.project_id in self.controller.serial_windows)
        dialog = self.controller.serial_windows[project.project_id]
        self.assertFalse(self.serial_harness.sessions)
        QTest.mouseClick(dialog.open_button, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: not dialog.busy and len(self.serial_harness.sessions) == 2)
        return project.project_id, dialog

    def _capture_serial(self, dialog, filename):
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            self.assertTrue(dialog.grab().save(str(Path(output) / filename)))

    def test_qt_serial_manual_send_confirmation_and_responsive_layout(self):
        from PySide6.QtWidgets import QMessageBox
        identifier, dialog = self._open_serial_fixture()
        view = dialog.views['vlan116']
        driver = self.serial_harness.drivers['COM216']
        driver.input.put(('模拟设备 RX（未连接硬件）\n' + '\n'.join('boot log ' + str(n) for n in range(450)) + '\n').encode())
        self.wait_for(lambda: 'boot log 449' in view['output'].toPlainText())
        view['input'].setText('echo fixture')
        QTest.keyClick(view['input'], Qt.Key.Key_Return)
        self.wait_for(lambda: not dialog.busy and driver.writes == [b'echo fixture\r'])
        self.assertEqual(view['input'].text(), '')
        view['input'].setText('reboot')
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
            QTest.keyClick(view['input'], Qt.Key.Key_Return)
            self.wait_for(lambda: not dialog.busy and '取消' in dialog.feedback.text())
        self.assertEqual(driver.writes, [b'echo fixture\r'])
        self.assertEqual(view['input'].text(), 'reboot')
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.keyClick(view['input'], Qt.Key.Key_Return)
            self.wait_for(lambda: not dialog.busy and len(driver.writes) == 2)
        self.assertEqual(driver.writes[-1], b'reboot\r')
        view['input'].setText('must-not-be-sent-by-enter-button')
        QTest.mouseClick(view['enter'], Qt.MouseButton.LeftButton)
        self.wait_for(lambda: not dialog.busy and len(driver.writes) == 3)
        self.assertEqual(driver.writes[-1], b'\r')
        for size, name in (((1040, 660), 'serial-terminal-wide.png'), ((620, 420), 'serial-terminal-small.png')):
            dialog.resize(*size)
            self.app.processEvents()
            self.assertTrue(dialog.open_button.isVisible())
            self.assertTrue(view['input'].isVisible())
            self.assertLessEqual(view['input'].geometry().right(), view['page'].width())
            self.assertEqual(view['output'].horizontalScrollBar().maximum(), 0)
            self._capture_serial(dialog, name)
        with patch('PySide6.QtWidgets.QFileDialog.getExistingDirectory', return_value=str(self.root / 'new-serial-logs')):
            QTest.mouseClick(dialog.directory_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not dialog.busy and identifier in dialog.path.text())
        original = self.serial_harness.sessions['COM216'].log_path
        self.assertNotIn('new-serial-logs', str(original))
        QTest.mouseClick(dialog.stop_button, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: not dialog.busy and all('已停止' in v['status'].text() for v in dialog.views.values()))
        text = original.read_text(encoding='utf-8')
        view['output'].clear()
        self.assertEqual(original.read_text(encoding='utf-8'), text)
        dialog.close()
        self.wait_for(lambda: identifier not in self.controller.serial_windows)

    def test_qt_serial_passive_snapshot_after_display_clear(self):
        from PySide6.QtWidgets import QLabel, QPlainTextEdit
        from src.models.serial_models import SerialSettings
        identifier, dialog = self._open_serial_fixture()
        driver = self.serial_harness.drivers['COM216']
        manager = self.controller.adapter._executions[identifier].manager
        manager.acquire_existing_control('fixture-active-job', SerialSettings('COM216'))
        output = dialog.views['vlan116']['output']
        driver.input.put(b'passive snapshot fixture\n')
        self.wait_for(lambda: 'passive snapshot fixture' in output.toPlainText())
        menu = dialog.create_output_menu('vlan116')
        actions = {action.text(): action for action in menu.actions()}
        actions['清屏（仅清显示）'].trigger()
        self.assertEqual(output.toPlainText(), '')
        actions['查看串口诊断快照…'].trigger()
        menu.deleteLater()
        self.wait_for(lambda: dialog.diagnostic_window is not None and not dialog.busy)
        snapshot = dialog.diagnostic_window
        received = snapshot.findChild(QPlainTextEdit)
        self.assertTrue(snapshot.isVisible() and received.isReadOnly())
        self.assertIn('vlan116 / COM216', snapshot.windowTitle())
        self.assertIn('fixture-active-job', snapshot.findChild(QLabel).text())
        self.assertIn('passive snapshot fixture', received.toPlainText())
        driver.input.put(b'later fixture output\n')
        self.wait_for(lambda: 'later fixture output' in output.toPlainText())
        self.assertNotIn('later fixture output', received.toPlainText())
        self.assertFalse(driver.writes)
        self.assertEqual(manager.diagnostic_state('COM216')['control_owner'], 'fixture-active-job')
        self._capture_serial(snapshot, 'serial-diagnostic-snapshot.png')
        manager.release('fixture-active-job', 'COM216')
        dialog.close()
        self.wait_for(lambda: identifier not in self.controller.serial_windows)
        self.assertIsNone(dialog.diagnostic_window)

    def test_qt_serial_close_worker_refusal_keeps_live_output_until_retry(self):
        from PySide6.QtWidgets import QMessageBox
        from src.models.serial_models import SerialSettings
        identifier, dialog = self._open_serial_fixture(('COM7960', 'COM7961'))
        manager = self.controller.adapter._executions[identifier].manager
        view = dialog.views['vlan116']
        index = dialog.tabs.indexOf(view['page'])
        dialog.tabs.setCurrentIndex(index)
        driver = self.serial_harness.drivers['COM7960']
        start = threading.Thread.start

        def fail_close(worker):
            if worker.name == 'serial-close-COM7960':
                raise RuntimeError('模拟收尾线程未启动')
            start(worker)

        with patch.object(threading.Thread, 'start', fail_close), \
                patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
                patch.object(QMessageBox, 'warning') as warning:
            dialog.close_tab(index)
            self.wait_for(lambda: warning.called and not dialog.busy)
        self.assertIn('COM7960 停止请求未受理，原监控继续', dialog.feedback.text())
        self.assertIs(manager.existing_session(SerialSettings('COM7960')), self.serial_harness.sessions['COM7960'])
        driver.input.put(b'RX after refused close\r\n')
        self.wait_for(lambda: 'RX after refused close' in view['output'].toPlainText())
        self._capture_serial(dialog, 'serial-close-retry.png')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            dialog.close_tab(index)
            self.wait_for(lambda: 'vlan116' not in dialog.views)
        self.assertTrue(driver.closed)
        self.assertFalse(self.serial_harness.drivers['COM7961'].closed)
        self.assertFalse(driver.writes)
        dialog.close()
        self.wait_for(lambda: identifier not in self.controller.serial_windows)

    def test_qt_serial_shared_owner_close_confirmation_and_control_lock(self):
        from PySide6.QtWidgets import QMessageBox
        from src.models.serial_models import SerialSettings
        identifier, dialog = self._open_serial_fixture()
        execution = self.controller.adapter._executions[identifier]
        manager = execution.manager
        manager.acquire_monitor('fixture-other-owner', SerialSettings('COM216'))
        view = dialog.views['vlan116']
        index = dialog.tabs.indexOf(view['page'])
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
            dialog.close_tab(index)
            self.wait_for(lambda: not dialog.busy)
        self.assertIn('vlan116', dialog.views)
        manager.acquire_control('fixture-upgrade', SerialSettings('COM216'))
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
             patch('PySide6.QtWidgets.QMessageBox.warning') as warning:
            dialog.close_tab(index)
            self.wait_for(lambda: warning.called and not dialog.busy)
        self.assertIn('vlan116', dialog.views)
        manager.release('fixture-upgrade', 'COM216')
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            dialog.close_tab(index)
            self.wait_for(lambda: 'vlan116' not in dialog.views)
        self.assertFalse(self.serial_harness.drivers['COM216'].closed)
        self.assertTrue(dialog.isVisible())
        self.controller.open_serial()
        self.wait_for(lambda: 'vlan116' in dialog.views and not dialog.busy)
        self.assertIn('未打开', dialog.views['vlan116']['status'].text())
        self.assertEqual(len(self.serial_harness.sessions), 2)
        dialog.open_button.click()
        self.wait_for(lambda: not dialog.busy and '监控中' in dialog.views['vlan116']['status'].text())
        # COM222 is now first: let its real close ticket complete, then refuse
        # the terminal's release on the reshown, shared COM216 tab.
        release = manager.release

        def release_monitor(owner, port, **options):
            if port == 'COM216':
                raise OSError('fixture release refused')
            return release(owner, port, **options)

        with patch.object(manager, 'release', side_effect=release_monitor), \
                patch.object(QMessageBox, 'warning') as warning:
            dialog.close()
            self.wait_for(lambda: warning.called and not dialog.busy)
        self.wait_for(lambda: 'vlan122' not in dialog.views and not dialog.detaching and dialog.stop_button.isEnabled())
        self.assertTrue(dialog.isVisible())
        self.assertIn('监控中', dialog.views['vlan116']['status'].text())
        self.assertTrue(self.serial_harness.drivers['COM222'].closed)
        dialog.close()
        self.wait_for(lambda: identifier not in self.controller.serial_windows)
        self.assertFalse(self.serial_harness.drivers['COM216'].closed)
        manager.release('fixture-other-owner', 'COM216')

    def test_qt_serial_window_minimize_and_pin_preserve_live_session(self):
        from ctypes import WinDLL, wintypes
        from PySide6.QtWidgets import QLabel, QMenu
        from src.ui.qt.window_placement import current_placement

        user32 = WinDLL('user32')
        user32.GetWindowLongW.argtypes = (wintypes.HWND, wintypes.INT)
        user32.GetWindowLongW.restype = wintypes.LONG
        user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
        user32.GetWindow.restype = wintypes.HWND
        user32.IsIconic.argtypes = (wintypes.HWND,)
        user32.IsIconic.restype = wintypes.BOOL
        user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.SendMessageW.restype = wintypes.LPARAM

        identifier, dialog = self._open_serial_fixture()
        session = self.serial_harness.sessions['COM222']
        driver = self.serial_harness.drivers['COM222']
        view = dialog.views['vlan122']
        dialog.tabs.setCurrentWidget(view['page'])
        output = view['output']
        driver.input.put(('\n'.join(f'pin fixture {n}' for n in range(240)) + '\n').encode())
        self.wait_for(lambda: 'pin fixture 239' in output.toPlainText())
        output.verticalScrollBar().setValue(output.verticalScrollBar().maximum() // 2)
        line = output.firstVisibleBlock().text()
        geometry = dialog.geometry()
        placement = current_placement(dialog)

        def extended_style():
            return user32.GetWindowLongW(int(dialog.winId()), -20)  # GWL_EXSTYLE

        hwnd = int(dialog.winId())
        self.assertTrue(user32.GetWindowLongW(hwnd, -16) & 0x20000)  # WS_MINIMIZEBOX
        self.assertFalse(user32.GetWindow(hwnd, 4))  # GW_OWNER
        self.assertFalse(extended_style() & 0x88)  # WS_EX_TOOLWINDOW | WS_EX_TOPMOST

        menu = dialog.create_output_menu('vlan122')
        action = next(action for action in menu.actions() if action.text() == '窗口置顶')
        self.assertTrue(action.isCheckable())
        self.assertFalse(action.isChecked())
        action.trigger()
        menu.deleteLater()
        self.wait_for(lambda: extended_style() & 0x8)  # WS_EX_TOPMOST
        self.assertEqual(dialog.geometry(), geometry)
        self.assertEqual(dialog.active, 'vlan122')
        self.assertEqual(output.firstVisibleBlock().text(), line)

        user32.SendMessageW(int(dialog.winId()), 0x112, 0xF020, 0)  # WM_SYSCOMMAND / SC_MINIMIZE
        self.wait_for(lambda: dialog.isMinimized() and user32.IsIconic(int(dialog.winId())))
        self.assertEqual(current_placement(dialog), placement)
        self.assertFalse(self.window.isMinimized())
        driver.input.put(b'recorded while minimized\n')
        self.wait_for(lambda: 'recorded while minimized' in session.log_path.read_text(encoding='utf-8'))
        self.assertIs(self.serial_harness.sessions['COM222'], session)
        self.assertFalse(driver.closed)

        self.controller.submit('create', self.root / 'other-serial', '另一个串口项目')
        self.wait_for(lambda: len(self.window.projects) == 2 and self.window.selected_project != identifier)
        other = self.window.selected_project
        self.controller.open_serial()
        self.wait_for(lambda: other in self.controller.serial_windows)
        self.assertFalse(self.controller.serial_windows[other].pin_action.isChecked())
        self.assertTrue(dialog.isMinimized())

        user32.SendMessageW(int(dialog.winId()), 0x112, 0xF120, 0)  # WM_SYSCOMMAND / SC_RESTORE
        self.wait_for(lambda: not dialog.isMinimized() and not user32.IsIconic(int(dialog.winId())))
        self.assertTrue(extended_style() & 0x8)
        dialog.showMinimized()
        self.window.select_project(identifier)
        self.controller.open_serial()
        self.wait_for(lambda: not dialog.isMinimized() and 'recorded while minimized' in output.toPlainText())
        self.assertIs(self.controller.serial_windows[identifier], dialog)
        self.assertTrue(action.isChecked())
        self.assertTrue(extended_style() & 0x8)
        self.assertEqual(dialog.geometry(), geometry)
        self.assertEqual(output.firstVisibleBlock().text(), line)

        title = next(widget for widget in dialog.findChildren(QLabel) if widget.text() == dialog.windowTitle())
        title_actions = []

        def select_pin():
            for title_menu in dialog.findChildren(QMenu):
                title_actions.extend(title_menu.actions())
                if action in title_menu.actions():
                    QTest.mouseClick(title_menu, Qt.MouseButton.LeftButton,
                                     pos=title_menu.actionGeometry(action).center())
                title_menu.close()

        QTimer.singleShot(0, select_pin)
        title.customContextMenuRequested.emit(title.rect().center())
        self.assertEqual(title_actions, [action])
        self.wait_for(lambda: not extended_style() & 0x8)
        self.assertEqual(dialog.geometry(), geometry)
        self.assertEqual(dialog.active, 'vlan122')
        self.assertEqual(output.firstVisibleBlock().text(), line)
        messages = {'[串口日志] 已置顶', '[串口日志] 已取消置顶', '[串口日志] 已最小化', '[串口日志] 已恢复窗口'}
        self.wait_for(lambda: messages <= {entry.message for entry in self.window.logs.entries
                                           if entry.project_id == identifier})

        dialog.showMinimized()
        self.wait_for(dialog.isMinimized)
        self.window.close()
        self.wait_for(lambda: self.controller.adapter.closed.is_set() and not self.window.isVisible())
        self.assertFalse(self.controller.serial_windows)
        self.assertTrue(driver.closed)

    def test_qt_serial_scroll_project_switch_and_exit_wait_for_reader(self):
        identifier, dialog = self._open_serial_fixture()
        view = dialog.views['vlan116']
        session = self.serial_harness.sessions['COM216']
        driver = self.serial_harness.drivers['COM216']
        driver.input.put(('\n'.join('fixture line ' + str(n) for n in range(600)) + '\n').encode())
        self.wait_for(lambda: 'fixture line 599' in view['output'].toPlainText())
        bar = view['output'].verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        position = bar.value()
        driver.input.put(b'reading-tail\n')
        self.wait_for(lambda: 'reading-tail' in view['output'].toPlainText())
        self.assertEqual(bar.value(), position)
        anchor = view['output'].firstVisibleBlock().text()
        view['output'].document().setMaximumBlockCount(650)
        dialog.append_output(view['output'], '\n'.join('trim fixture ' + str(n) for n in range(100)) + '\n')
        self.assertEqual(view['output'].firstVisibleBlock().text(), anchor)
        view['output'].document().setMaximumBlockCount(5000)
        bar.setValue(bar.maximum())
        driver.input.put(b'follow-tail\n')
        self.wait_for(lambda: 'follow-tail' in view['output'].toPlainText())
        self.assertEqual(bar.value(), bar.maximum())
        self.controller.submit('create', self.root / 'other-project', '切页目标项目')
        self.wait_for(lambda: len(self.window.projects) == 2 and self.window.selected_project != identifier)
        self.window.show_dashboard()
        self.assertIs(self.controller.serial_windows[identifier], dialog)
        self.assertFalse(driver.closed)
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def blocked(event):
            if event.direction == 'RX':
                entered.set()
                release.wait(3)
        session.subscribe(blocked)
        driver.input.put(b'final-half-line')
        self.assertTrue(entered.wait(2))
        self.window.close()
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        self.app.processEvents()
        self.assertTrue(ticks)
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.controller.adapter.closed.is_set())
        release.set()
        self.wait_for(lambda: self.controller.adapter.closed.is_set())
        self.wait_for(lambda: not self.window.isVisible())
        self.assertTrue(driver.closed)
        self.assertIn('RX final-half-line', session.log_path.read_text(encoding='utf-8'))

    def test_qt_postrun_resume_shows_waiting_and_cancels_remaining_channels(self):
        from PySide6.QtWidgets import QMessageBox
        from qt_execution_fakes import ControlledResumePipeline

        _, identifier = self._configured_execution(numbers=(1, 7, 9, 11))
        harness = ControlledResumePipeline()
        harness.recovery_gates = {n: threading.Event() for n in (7, 9, 11)}
        self.addCleanup(harness.release_recovery.set)
        self.addCleanup(harness.finish.set)
        self.window.select_project(identifier)
        detail = self.window.detail
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        yes = QMessageBox.StandardButton.Yes

        def submit(number):
            detail.channel_context_menu(number, detail.channels.mapToGlobal(QPoint(6, 6)))
            self.wait_for(detail.recovery_menu.isVisible)
            self.assertTrue(detail.recovery_action.isEnabled())
            detail.recovery_menu.hide()
            detail.recovery_action.trigger()

        with patch('src.services.capability_device_services.PipelineOrchestrator', harness.factory), \
                patch('src.services.legacy_power_test_service.run_legacy_power_test', harness.run_after_exit), \
                patch('PySide6.QtWidgets.QMessageBox.question', return_value=yes) as prompt:
            self.controller.start_test()
            self.wait_for(harness.started.is_set)
            harness.finish.set()
            self.wait_for(lambda: detail.project.state == 'failed' and detail.project.channels[6].can_resume)
            submit(7)
            self.wait_for(lambda: harness.recovering.is_set() and 'CH07 · 续跑中' in detail.stage.text())
            submit(11)
            self.wait_for(lambda: detail.project.resume_waiting == (11,))
            self.assertIn('加入等待队列', prompt.call_args.args[2])
            submit(9)
            self.wait_for(lambda: detail.project.resume_waiting == (11, 9))
            self.assertFalse(detail.project.channels[10].can_resume)
            self.assertEqual(len(harness.recovery_calls), 1)
            self.assertIn('排队 CH11、CH09', detail.stage.text())
            if output:
                self.assertTrue(self.window.grab().save(str(Path(output) / 'resume-queue-waiting.png')))
            harness.recovery_gates[7].set()
            self.wait_for(lambda: len(harness.recovery_calls) == 2 and 'CH11 · 续跑中' in detail.stage.text())
            self.assertEqual(detail.project.resume_waiting, (9,))
            QTest.mouseClick(detail.stop_button, Qt.MouseButton.LeftButton)
            self.wait_for(harness.observed_stop.is_set)
            self.assertIn('取消等待续跑的通道：CH09', prompt.call_args.args[2])
            harness.recovery_gates[11].set()
            self.wait_for(lambda: '续跑已停止' in detail.stage.text() and not detail.project.active_task_count)
            self.assertEqual(detail.project.resume_waiting, ())
            self.assertEqual(detail.project.state, 'failed')
            self.assertEqual([request.channels[0].number for request, _ in harness.recovery_calls], [7, 11])
            if output:
                self.assertTrue(self.window.grab().save(str(Path(output) / 'resume-queue-stopped.png')))

    def test_qt_channel_log_menu_preserves_project_and_current_wifi_attempt(self):
        from PySide6.QtWidgets import QMessageBox
        from qt_execution_fakes import ControlledResumePipeline

        _, identifier = self._configured_execution()
        harness = ControlledResumePipeline()
        self.addCleanup(harness.finish.set)
        self.addCleanup(harness.release_recovery.set)
        detail = self.window.detail
        self.window.select_project(identifier)
        with patch('src.services.capability_device_services.PipelineOrchestrator', harness.factory), \
                patch('src.services.qt_power_logs.os.startfile') as shell_open:
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                self.controller.start_test()
                self.wait_for(harness.started.is_set)
            session = harness.session
            directory = session.request.tool_root / 'test_results/device_7'
            directory.mkdir(parents=True)
            power = directory / 'device_7_command_results_20261120220000.log'
            wifi = directory / 'device_7_wifi_20261120220000.log'
            power.write_text('合成开关机结果', encoding='utf-8')
            wifi.write_text('原尝试 WiFi 记录', encoding='utf-8')
            session.observe(dict(type='wifi_log_created', run_id=session.run_id, channel=7, attempt=0, path=str(wifi)))

            tile = detail.channels.tiles[1]
            tile.customContextMenuRequested.emit(tile.rect().center())
            self.wait_for(detail.recovery_menu.isVisible)
            self.assertEqual(detail.recovery_action.data(), (identifier, 7))
            output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if output:
                self.assertTrue(detail.recovery_menu.grab().save(str(Path(output) / 'power-log-channel-menu.png')))
            detail.recovery_menu.hide()
            detail.power_log_actions['power'].trigger()
            self.wait_for(lambda: shell_open.call_count == 1)
            shell_open.assert_called_once_with(str(power))

            detail.set_channel_mode(1)
            table = detail.channel_table
            index = detail.channel_model.index(1, 0)
            table.scrollTo(index)
            self.app.processEvents()
            table.customContextMenuRequested.emit(table.visualRect(index).center())
            self.wait_for(detail.recovery_menu.isVisible)
            detail.recovery_menu.hide()
            self.assertEqual(detail.recovery_action.data(), (identifier, 7))
            detail.power_log_actions['wifi'].trigger()
            self.wait_for(lambda: shell_open.call_count == 2)
            self.assertEqual(shell_open.call_args.args, (str(wifi),))

            with session.lock:
                session.attempts[7] = 1
            detail.power_log_actions['wifi'].trigger()
            self.wait_for(lambda: '本次执行尝试尚未生成 WiFi 日志' in self.window.statusBar().currentMessage())
            self.assertEqual(shell_open.call_count, 2)
            self.controller.submit('create', self.root / 'log-other', '不同日志项目')
            self.wait_for(lambda: len(self.window.projects) == 2)
            other = next(p.project_id for p in self.window.projects if p.project_id != identifier)
            self.window.select_project(other)
            new_wifi = directory / 'device_7_wifi_20261120220100_resume1.log'
            new_wifi.write_text('当前尝试 WiFi 记录', encoding='utf-8')
            session.observe(dict(type='wifi_log_created', run_id=session.run_id, channel=7, attempt=1, path=str(new_wifi)))
            detail.power_log_actions['wifi'].trigger()
            self.wait_for(lambda: shell_open.call_count == 3)
            self.assertEqual(shell_open.call_args.args, (str(new_wifi),))
            self.assertEqual(self.window.selected_project, other)
            self.assertEqual(wifi.read_text(encoding='utf-8'), '原尝试 WiFi 记录')
            self.assertFalse(harness.finish.is_set())
            harness.finish.set()
            self.wait_for(lambda: not self.controller.adapter._service.resources.owners)

    def test_qt_channel_history_follows_original_batch_and_after_run_resume(self):
        from PySide6.QtWidgets import QMessageBox
        from qt_execution_fakes import ControlledResumePipeline

        _, identifier = self._configured_execution()
        harness = ControlledResumePipeline()
        self.addCleanup(harness.finish.set)
        self.addCleanup(harness.release_recovery.set)
        detail = self.window.detail
        history = self.controller.channel_history
        self.window.select_project(identifier)
        yes = QMessageBox.StandardButton.Yes
        with patch('src.services.capability_device_services.PipelineOrchestrator', harness.factory), \
                patch('src.services.legacy_power_test_service.run_legacy_power_test', harness.run_after_exit):
            with patch.object(QMessageBox, 'question', return_value=yes):
                self.controller.start_test()
                self.wait_for(harness.started.is_set)
            self.wait_for(lambda: detail.project.power_history_job and detail.project.channels[6].detail == '模拟状态')
            parent = detail.project.power_history_job
            tile = detail.channels.tiles[1]
            tile.customContextMenuRequested.emit(tile.rect().center())
            self.wait_for(detail.recovery_menu.isVisible)
            self.assertEqual(detail.channel_history_action.data(), (identifier, parent, 7))
            detail.recovery_menu.hide()
            detail.channel_history_action.trigger()
            self.wait_for(lambda: history.dialog is not None and '暂无' in history.dialog.feedback.text())
            dialog = history.dialog
            self.assertFalse(dialog.isModal())
            self.assertTrue(dialog.body.isReadOnly())
            record = harness.session.callbacks['on_channel_history']
            record(1, 2, 'failed', '其它通道的原因')
            record(7, 3, 'retry', '5 GHz 扫描超时 <原始原因>')
            record(7, 3, 'failed', '5 GHz 无法连接')
            self.wait_for(lambda: '5 GHz 无法连接' in dialog.body.toPlainText())
            self.assertEqual(dialog.body.toPlainText().splitlines(),
                ['第 3 轮｜重试：5 GHz 扫描超时 <原始原因>', '第 3 轮｜失败：5 GHz 无法连接'])

            self.controller.submit('create', self.root / 'history-other', '其它历史项目')
            self.wait_for(lambda: len(self.window.projects) == 2)
            other = next(p.project_id for p in self.window.projects if p.project_id != identifier)
            self.window.select_project(other)
            self.assertIs(history.dialog, dialog)
            harness.finish.set()
            self.window.select_project(identifier)
            self.wait_for(lambda: detail.project.state == 'failed' and detail.project.channels[6].can_resume)
            with patch.object(QMessageBox, 'question', return_value=yes):
                self.controller.resume_channel(identifier, 7)
                self.wait_for(harness.recovering.is_set)
            record(7, 4, 'resume', '从失败轮次继续')
            record(7, 4, 'success', '续跑原业务回调已记录结果')
            harness.release_recovery.set()
            self.wait_for(lambda: '重试后成功' in dialog.body.toPlainText() and not detail.project.active_task_count)
            self.assertEqual(dialog.target, (identifier, parent, 7))
            self.assertIn('第 4 轮｜续跑', dialog.body.toPlainText())
            self.assertNotIn('其它通道', dialog.body.toPlainText())
            output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if output:
                self.assertTrue(dialog.grab().save(str(Path(output) / 'channel-retry-history.png')))

        new_run = ControlledResumePipeline()
        self.addCleanup(new_run.finish.set)
        devices = self.controller.adapter._executions[identifier].capabilities.devices
        self.wait_for(lambda: detail.project.can_start)
        with patch.object(devices, 'pipeline_factory', new_run.factory), \
                patch.object(QMessageBox, 'question', return_value=yes):
            self.controller.start_test()
            self.wait_for(lambda: new_run.started.is_set() and history.dialog is None)
            self.assertNotEqual(detail.project.power_history_job, parent)
            self.controller.channel_history.open(identifier, parent, 7)
            self.assertIsNone(history.dialog)
            new_run.finish.set()
            self.wait_for(lambda: not detail.project.active_task_count)

    def test_qt_resume_matrix_list_confirmation_and_after_run_progress(self):
        from PySide6.QtWidgets import QMessageBox
        from qt_execution_fakes import ControlledResumePipeline
        _, identifier = self._configured_execution()
        harness = ControlledResumePipeline()
        self.addCleanup(harness.release_recovery.set)
        self.addCleanup(harness.finish.set)
        detail = self.window.detail
        self.window.select_project(identifier)
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')

        def ready():
            return any(row.number == 7 and row.can_resume for row in self.window.projects[0].channels)

        with patch('src.services.capability_device_services.PipelineOrchestrator', harness.factory), \
                patch('src.services.legacy_power_test_service.run_legacy_power_test', harness.run_after_exit):
            with patch('PySide6.QtWidgets.QMessageBox.question', return_value=yes):
                self.controller.start_test()
                self.wait_for(harness.started.is_set)
            self.wait_for(ready)
            self.assertFalse(detail.project.channels[0].can_resume)
            tile = detail.channels.tiles[1]
            tile.customContextMenuRequested.emit(tile.rect().center())
            self.wait_for(detail.recovery_menu.isVisible)
            self.assertTrue(detail.recovery_action.isEnabled())
            if output:
                self.assertTrue(detail.recovery_menu.grab().save(str(Path(output) / 'resume-channel-menu.png')))
            detail.recovery_menu.hide()
            with patch('PySide6.QtWidgets.QMessageBox.question', return_value=no) as prompt:
                detail.recovery_action.trigger()
                self.wait_for(lambda: prompt.called)
            self.assertEqual(prompt.call_args.args[1], '确认通道续跑')
            self.assertEqual(prompt.call_args.args[-1], no)
            self.assertIn('第 4/100 轮', prompt.call_args.args[2])
            self.assertTrue(harness.commands.empty())
            harness.finish.set()
            self.wait_for(lambda: self.window.projects[0].state == 'failed' and ready())
            detail.set_channel_mode(1)
            table = detail.channel_table
            index = detail.channel_model.index(1, 0)
            table.scrollTo(index)
            self.app.processEvents()
            table.customContextMenuRequested.emit(table.visualRect(index).center())
            self.wait_for(detail.recovery_menu.isVisible)
            self.assertEqual(detail.recovery_action.data(), (identifier, 7))
            detail.recovery_menu.hide()
            with patch('PySide6.QtWidgets.QMessageBox.question', return_value=yes):
                detail.recovery_action.trigger()
                self.wait_for(lambda: harness.recovering.is_set() and '续跑中' in detail.stage.text())
            self.assertTrue(detail.stop_button.isEnabled())
            self.assertEqual(detail.project.state, 'failed')
            harness.release_recovery.set()
            self.wait_for(lambda: '续跑完成' in detail.stage.text() and not detail.project.active_task_count)
        self.assertFalse(detail.stop_button.isEnabled())
        self.assertEqual(detail.project.state, 'failed')
        self.assertIn('执行失败', detail.stage.text())
        self.assertEqual(detail.project.progress, 100)
        self.app.processEvents()
        self.assertGreaterEqual(detail.percent.contentsRect().width(),
            detail.percent.fontMetrics().horizontalAdvance('100%'))
        self.assertEqual(detail.project.channels[6].cycle, 100)
        self.assertEqual(detail.project.channels[0].cycle, 100)
        self.assertEqual([entry.number for entry in harness.recovery_calls[0][0].channels], [7])
        if output:
            self.assertTrue(self.window.grab().save(str(Path(output) / 'resume-channel-finished.png')))

    def test_qt_pipeline_choices_prestart_original_serial_terminal_before_environment(self):
        from PySide6.QtWidgets import QCheckBox, QMessageBox
        from qt_serial_fakes import SerialHarness
        from src.models.capabilities import CapabilityError
        from src.services.pipeline_orchestrator import PipelineOrchestrator
        _, identifier = self._configured_execution()
        serial = SerialHarness().start()
        self.addCleanup(serial.stop)
        self.window.detail.pipeline_button.click()
        self.wait_for(lambda: identifier in self.controller.pipeline_windows
                      and bool(self.controller.pipeline_windows[identifier].ready))
        dialog = self.controller.pipeline_windows[identifier]
        execution = self.controller.adapter._executions[identifier]
        execution.capabilities.devices.pipeline_factory = PipelineOrchestrator
        self.assertEqual(tuple(dialog.checks), ('env_check', 'serial_terminal', 'legacy_power_test'))
        self.assertEqual([check.text() for check in dialog.findChildren(QCheckBox)], [
            '1. 环境线路检查', '2. 串口日志', '3. 执行开关机测试',
        ])
        self.assertEqual(dialog.selection(), ())
        self.assertFalse(dialog.start_button.isEnabled())
        for code in ('env_check', 'serial_terminal'):
            dialog.checks[code].setChecked(True)
        self.wait_for(dialog.start_button.isEnabled)
        directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if directory:
            self.assertTrue(dialog.grab().save(str(Path(directory) / 'pipeline-options.png')))
        no, yes = QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes
        with patch.object(QMessageBox, 'question', return_value=no) as refuse:
            dialog.start_button.click()
            self.wait_for(lambda: refuse.called and execution.pending is None)
        self.assertFalse(serial.sessions)
        summary = refuse.call_args.args[2]
        self.assertIn('串口日志 → 环境线路检查', summary)
        self.assertIn('子任务', summary)
        self.assertNotIn('管道', summary)

        # Verification can fail after the operator has already confirmed.
        with patch.object(QMessageBox, 'question', return_value=yes), \
                patch.object(QMessageBox, 'warning') as warn, \
                patch.object(execution, '_verify_nics', side_effect=CapabilityError(
                    'configuration_changed', '确认后网卡配置已变化，未执行')):
            self.wait_for(dialog.start_button.isEnabled)
            dialog.start_button.click()
            self.wait_for(lambda: warn.called and execution.pending is None)
        self.assertIn('确认后网卡配置已变化', warn.call_args.args[2])
        self.assertTrue(dialog.isVisible())
        self.assertFalse(serial.sessions)
        self.assertFalse(execution.jobs)
        entered = []

        def environment(_):
            self.assertEqual(set(serial.sessions), {'COM1', 'COM7'})
            entered.append(True)

        with patch.object(QMessageBox, 'question', return_value=yes), \
                patch.object(PipelineOrchestrator, '_run_env_check', environment):
            self.wait_for(dialog.start_button.isEnabled)
            dialog.start_button.click()
            self.wait_for(lambda: entered and identifier in self.controller.serial_windows
                          and '环境线路检查完成' in dialog.feedback.text() and not dialog.isVisible())
        # The job publishes its terminal result before releasing resources and exiting.
        self.wait_for(lambda: execution.idle)
        self.assertTrue(execution.terminal.tabs['vlan107']['path'])
        self.assertFalse(dialog.isVisible())
        self.controller.open_pipeline()
        self.wait_for(lambda: dialog.isVisible() and dialog.start_button.isEnabled())
        if directory:
            self.assertTrue(dialog.grab().save(str(Path(directory) / 'pipeline-completed.png')))

    def test_qt_disjoint_project_power_starts_and_stop_is_project_scoped(self):
        from PySide6.QtWidgets import QMessageBox
        from line_check_assistant.config_store import ChannelConfigStore
        from qt_execution_fakes import ControlledPipeline, configure_project

        first_engine, first = self._configured_execution(numbers=(1,))
        workspace = self.controller.adapter._service
        self.controller.submit('create', self.root / 'second-power', '第二电源项目')
        self.wait_for(lambda: len(self.window.projects) == 2)
        second = next(p.project_id for p in self.window.projects if p.project_id != first)
        context = workspace.projects.opened[second]
        nics = configure_project(workspace, context, numbers=(8,))
        store = ChannelConfigStore(context.config_dir / 'network_card_ip.ini')
        store.save(store.load(), 'COM803')
        workspace.projects.save(context)
        self.controller.submit('refresh')
        self.window.select_project(first)
        second_engine = ControlledPipeline()
        try:
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                self.wait_for(self.window.detail.start_button.isEnabled)
                self.window.detail.start_button.click()
                self.wait_for(first_engine.started.is_set)
                self.window.select_project(second)
                self.wait_for(lambda: self.window.detail.project.parallel_power_available)
                self.assertTrue(self.window.detail.start_button.isEnabled())
                self.assertFalse(self.window.detail.environment_button.isEnabled())
                with patch('src.core.network_adapter.read_adapter_identities', return_value=nics), \
                        patch('src.services.capability_device_services.PipelineOrchestrator', second_engine.factory):
                    self.window.detail.start_button.click()
                    self.wait_for(second_engine.started.is_set)
                self.wait_for(lambda: all(p.state == 'running' for p in self.window.projects))
                self.window.show_dashboard()
                directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
                if directory:
                    self.app.processEvents()
                    self.assertTrue(self.window.grab().save(str(Path(directory) / 'parallel-power-projects.png')))
                self.window.select_project(first)
                self.window.detail.stop_button.click()
                self.wait_for(first_engine.stop_observed.is_set)
                first_engine.release_stop.set()
                self.wait_for(lambda: self.window.detail.project.state == 'stopped')
                self.window.select_project(second)
                self.assertEqual(self.window.detail.project.state, 'running')
                self.assertFalse(second_engine.stop_observed.is_set())
                second_engine.finish.set()
                self.wait_for(lambda: self.window.detail.project.state == 'completed')
        finally:
            first_engine.finish.set()
            first_engine.release_stop.set()
            second_engine.finish.set()
            second_engine.release_stop.set()

    def test_qt_start_switch_stop_and_exit_wait_for_original_job(self):
        from datetime import datetime
        from PySide6.QtWidgets import QMessageBox
        engine, identifier = self._configured_execution()
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(self.window.detail.start_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: engine.started.is_set())
            self.wait_for(lambda: self.window.projects[0].progress == 68)
            detail = self.window.detail
            self.wait_for(lambda: 'fixture stage' in detail.channels.tiles[0].toolTip())
            self.assertIn('已完成 68 轮', detail.channels.tiles[0].text())
            self.assertIn('最近上报：fixture stage', detail.channel_model.index(0, 1).data())
            detail.channels.tiles[0].click()
            from PySide6.QtWidgets import QLabel
            snapshot = detail.dialogs[-1]
            fields = [widget.text() for widget in snapshot.findChildren(QLabel)]
            self.assertIn('最近上报阶段', fields)
            self.assertEqual(fields.count('fixture stage'), 1)
            self.assertIn('目标轮次', fields)
            self.assertIn('100', fields)
            directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if directory:
                self.assertTrue(snapshot.grab().save(str(Path(directory) / 'channel-reported-stage.png')))
            snapshot.close()
            self.window.mode_label.setText('模拟设备验证 · 原任务服务（不连接硬件）')
            self.assertTrue(self.window.detail.stop_button.isEnabled())
            self.assertFalse(self.window.detail.start_button.isEnabled())
            self.assertEqual(self.window.projects[0].active_task_count, 1)
            job = self.window.projects[0].run_id
            ledger = self.controller.adapter._service.status
            with ledger.lock:
                started = datetime.fromtimestamp(ledger.records[job]['started_at'])
            expected_start = '开始于 ' + started.strftime('%Y-%m-%d %H:%M:%S')
            self.assertIn(expected_start, self.window.detail.metadata.text())
            self.window.show_dashboard()
            self.app.processEvents()
            self.window.select_project(identifier)
            self.assertEqual(self.window.projects[0].run_id, job)
            self.assertIn(expected_start, self.window.detail.metadata.text())
            self.assertEqual(len(engine.calls), 1)
            self.assertFalse(engine.stop_observed.is_set())
            output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if output:
                self.window.resize(1366, 768)
                self.app.processEvents()
                self.assertTrue(self.window.grab().save(str(Path(output) / 'power-test-running.png')))
            QTest.mouseClick(self.window.detail.stop_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: engine.stop_observed.is_set())
            self.wait_for(lambda: self.window.projects[0].state == 'stopping')
            self.assertTrue(self.controller.adapter._service.resources.owners)
            if output:
                self.assertTrue(self.window.grab().save(str(Path(output) / 'power-test-stopping.png')))
            ticks = []
            QTimer.singleShot(0, lambda: ticks.append(True))
            self.window.close()
            self.app.processEvents()
            self.assertTrue(ticks)
            self.assertTrue(self.window.isVisible())
            self.assertFalse(self.controller.adapter.closed.is_set())
            engine.release_stop.set()
            self.wait_for(lambda: self.controller.adapter.closed.is_set())
            self.wait_for(lambda: not self.window.isVisible())
            self.assertFalse(self.controller.adapter.thread.is_alive())

    def test_qt_operator_stop_waits_for_original_process_receipt(self):
        from threading import Event
        from PySide6.QtWidgets import QMessageBox
        from src.services import legacy_power_test_service as legacy
        from src.services.pipeline_orchestrator import PipelineOrchestrator
        from test_legacy_power_test_service import _CompletedProcess, _FakeProcessContext
        _, project = self._configured_execution(numbers=(1,))
        started, stopping, allow_exit = Event(), Event(), Event()

        class SimulatedPowerProcess(_CompletedProcess):
            def start(self):
                started.set()

            def is_alive(self):
                if self._alive and self.args[2].is_set():
                    stopping.set()
                    if allow_exit.is_set():
                        self.args[1].put(dict(type='result', run_id=self.args[4], ok=False,
                                              detail='用户已停止执行开关机测试'))
                        self._alive = False
                return self._alive

        context = _FakeProcessContext()
        with patch('src.services.capability_device_services.PipelineOrchestrator', PipelineOrchestrator), \
                patch.object(legacy, 'multiprocessing') as spawn, \
                patch.object(context, 'Process', side_effect=SimulatedPowerProcess) as process, \
                patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            spawn.get_context.return_value = context
            self.window.detail.start_button.click()
            try:
                self.wait_for(lambda: started.is_set() and self.window.detail.stop_button.isEnabled())
                self.window.detail.stop_button.click()
                self.wait_for(stopping.is_set)
                execution = self.controller.adapter._executions[project]
                self.assertFalse(execution.idle)
                self.assertTrue(execution.workspace.resources.owners)
            finally:
                allow_exit.set()
            self.wait_for(lambda: self.window.projects[0].state == 'stopped')
            self.assertTrue(execution.idle)
            self.assertFalse(execution.workspace.resources.owners)
            row = execution.jobs[execution.latest]['status']
            self.assertEqual((row['state'], row['result']['ok']), ('stopped', False))
            self.assertIn('用户已停止执行开关机测试', row['result']['error'])
            self.assertIs(process.call_args.kwargs['target'], legacy._legacy_start_all_worker)
            self._capture_serial(self.window, 'power-stopped-receipt.png')

    def test_qt_declined_confirmation_never_starts_a_job(self):
        from PySide6.QtWidgets import QMessageBox
        engine, identifier = self._configured_execution()
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.No) as question:
            self.controller.start_test()
            self.wait_for(lambda: question.called)
        self.assertFalse(engine.calls)
        execution = self.controller.adapter._executions[identifier]
        self.assertIsNone(execution.capabilities)
        self.assertEqual(self.window.projects[0].active_task_count, 0)

    def test_qt_configuration_changed_during_confirmation_blocks_dispatch(self):
        from PySide6.QtWidgets import QMessageBox
        engine, identifier = self._configured_execution()
        workspace = self.controller.adapter._service
        context = workspace.projects.opened[identifier]
        def change_configuration(*args, **kwargs):
            config = context.config_dir / 'test_project_config.ini'
            config.write_bytes(config.read_bytes() + b'\n# changed before local approval\n')
            return QMessageBox.StandardButton.Yes
        with patch('PySide6.QtWidgets.QMessageBox.question', side_effect=change_configuration), \
             patch('PySide6.QtWidgets.QMessageBox.warning') as warning:
            self.controller.start_test()
            self.wait_for(lambda: warning.called)
        self.assertFalse(engine.calls)
        self.assertIn('配置', warning.call_args.args[2])
        self.assertIsNone(self.controller.adapter._executions[identifier].capabilities)
        self.assertEqual(self.window.projects[0].active_task_count, 0)

    def _open_configuration(self):
        self.controller.submit('create', self.root / 'configuration', '六标签配置验证')
        self.wait_for(lambda: len(self.window.projects) == 1)
        project = self.window.projects[0]
        self.assertTrue(self.window.detail.edit_button.isEnabled())
        QTest.mouseClick(self.window.detail.edit_button, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: project.project_id in self.controller.configuration_editors)
        return project.project_id, self.controller.configuration_editors[project.project_id]

    def test_qt_configuration_recovers_raw_editor_input_and_confirmed_discard(self):
        from PySide6.QtWidgets import QDialog, QLineEdit, QMessageBox

        identifier, dialog = self._open_configuration()
        context = self.controller.adapter._service.projects.opened[identifier]
        config = context.config_dir / 'test_project_config.ini'
        original = config.read_bytes()
        recovery = context.root / 'ui/qt_editor_recovery.json'
        dialog.fields['telnet']['port'].setText('-')
        dialog.fields['telnet']['password'].setText('private-recovery-fixture')
        dialog.interval.setText('incomplete')
        row = dialog.add_command()
        row['command'].setText('  unfinished fixture  ')
        row['retry'].clear()
        dialog.add_segment(row, dict(text='', negate=True))
        self.wait_for(lambda: '恢复草稿已保存' in dialog.feedback.text())
        self.assertNotIn(b'private-recovery-fixture', recovery.read_bytes())
        # Emulate losing the editor without accepting its normal discard prompt.
        dialog.done(QDialog.DialogCode.Rejected)
        self.wait_for(lambda: identifier not in self.controller.configuration_editors and self.window.detail.edit_button.isEnabled())
        self.assertTrue(recovery.exists())
        answers = QMessageBox.StandardButton
        with patch.object(QMessageBox, 'question', return_value=answers.Cancel) as question:
            self.controller.open_configuration()
            self.wait_for(lambda: question.called and identifier not in self.controller.configuration_editors)
        self.assertTrue(recovery.exists())
        self.wait_for(self.window.detail.edit_button.isEnabled)
        with patch.object(QMessageBox, 'question', return_value=answers.Yes):
            self.controller.open_configuration()
            self.wait_for(lambda: identifier in self.controller.configuration_editors)
        restored = self.controller.configuration_editors[identifier]
        self.assertTrue(restored.dirty)
        self.assertEqual(restored.fields['telnet']['port'].text(), '-')
        self.assertEqual(restored.fields['telnet']['password'].text(), 'private-recovery-fixture')
        self.assertEqual(restored.fields['telnet']['password'].echoMode(), QLineEdit.EchoMode.Password)
        self.assertEqual(restored.interval.text(), 'incomplete')
        self.assertEqual(restored.commands[-1]['command'].text(), '  unfinished fixture  ')
        self.assertEqual(restored.commands[-1]['retry'].text(), '')
        self.assertTrue(restored.commands[-1]['segments'][-1]['negate'].isChecked())
        self.assertEqual(config.read_bytes(), original)
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            restored.tabs.setCurrentIndex(1)
            self.scope.app.processEvents()
            Path(output).mkdir(parents=True, exist_ok=True)
            self.assertTrue(restored.grab().save(str(Path(output) / 'configuration-recovered-draft.png')))
        with patch.object(QMessageBox, 'question', return_value=answers.Yes):
            restored.close()
            self.wait_for(lambda: not recovery.exists())
        self.assertEqual(config.read_bytes(), original)

    def test_qt_six_configuration_tabs_save_and_reopen_original_values(self):
        from PySide6.QtWidgets import QCheckBox, QLineEdit, QMessageBox
        from line_check_assistant.test_item_config_store import TestItemConfigStore
        identifier, dialog = self._open_configuration()
        self.assertEqual([dialog.tabs.tabText(i) for i in range(dialog.tabs.count())],
            ['Telnet', '测试项', 'WiFi', '项目信息', '开关机运行参数', '消息推送'])
        dialog.fields['telnet']['password'].setText('qt-private-fixture')
        self.assertEqual(dialog.fields['telnet']['password'].echoMode(), QLineEdit.EchoMode.Password)
        visibility = next(c for c in dialog.tabs.widget(0).findChildren(QCheckBox) if c.text() == '显示')
        QTest.mouseClick(visibility, Qt.MouseButton.LeftButton, pos=QPoint(7, visibility.height() // 2))
        self.assertEqual(dialog.fields['telnet']['password'].echoMode(), QLineEdit.EchoMode.Normal)
        QTest.mouseClick(visibility, Qt.MouseButton.LeftButton, pos=QPoint(7, visibility.height() // 2))
        self.assertEqual(dialog.fields['telnet']['password'].echoMode(), QLineEdit.EchoMode.Password)
        no_password = dialog.fields['telnet']['telnet_no_user_password_flag']
        no_password.setCurrentIndex(no_password.findData(1))
        self.assertFalse(dialog.fields['telnet']['password'].isEnabled())
        self.assertEqual(dialog.fields['telnet']['password'].text(), 'qt-private-fixture')
        dialog.interval.setText('0')
        for row in tuple(dialog.commands):
            dialog.remove_command(row)
        row = dialog.add_command(dict(command='echo fixture', retry_times=3, expected_segments=[dict(text='first', negate=False)]))
        dialog.add_segment(row, dict(text='second', negate=True))
        dialog.fields['runtime']['number_of_tests'].setText('43')
        context = self.controller.adapter._service.projects.opened[identifier]
        old_revision = context.identity.revision
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not dialog.busy and not dialog.dirty and context.identity.revision != old_revision)
        loaded = TestItemConfigStore(context.config_dir / 'test_project_config.ini').load()
        self.assertEqual(loaded.telnet.password, 'qt-private-fixture')
        self.assertEqual(loaded.order.command_fail_retry_interval_time, 0)
        self.assertEqual(loaded.order.items[0].expected_segments[1].negate, True)
        self.assertFalse(self.window.detail.start_button.isEnabled())
        dialog.close()
        self.wait_for(lambda: not self.controller.adapter._executions[identifier].editor_open)
        self.controller.open_configuration()
        self.wait_for(lambda: identifier in self.controller.configuration_editors)
        dialog = self.controller.configuration_editors[identifier]
        self.assertEqual(dialog.fields['telnet']['password'].text(), 'qt-private-fixture')
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        with patch('src.core.wifi_interfaces.list_wifi_interface_names', return_value=['Fixture Wi-Fi', 'Fixture Wi-Fi 2']):
            dialog.request_wifi_interfaces()
            self.wait_for(lambda: not dialog.busy)
        card_field = dialog.fields['connect_wifi']['wireless_card_name']
        self.assertEqual(card_field.currentData(), 'Fixture Wi-Fi')
        self.assertTrue(dialog.dirty)
        for index, name in enumerate(('telnet', 'commands', 'wifi', 'project', 'runtime', 'push')):
            dialog.tabs.setCurrentIndex(index)
            self.app.processEvents()
            scroll = dialog.tabs.widget(index)
            self.assertEqual(scroll.horizontalScrollBar().maximum(), 0, name)
            self.assertTrue(dialog.rect().contains(dialog.save_button.mapTo(dialog, QPoint(0, 0))))
            if output:
                self.assertTrue(dialog.grab().save(str(Path(output) / ('configuration-' + name + '.png'))))
        dialog.resize(620, 460)
        dialog.tabs.setCurrentIndex(0)
        self.app.processEvents()
        self.assertEqual(dialog.tabs.widget(0).horizontalScrollBar().maximum(), 0)
        self.assertLessEqual(dialog.fields['telnet']['password'].width(), 460)
        if output:
            self.assertTrue(dialog.grab().save(str(Path(output) / 'configuration-small.png')))

    def test_qt_pretest_freezes_editor_draft_and_closing_requests_safe_stop(self):
        from PySide6.QtWidgets import QMessageBox
        from src.models.test_item_pretest_models import PretestResult
        engine, identifier = self._configured_execution()
        self.controller.open_configuration()
        self.wait_for(lambda: identifier in self.controller.configuration_editors)
        dialog = self.controller.configuration_editors[identifier]
        context = self.controller.adapter._service.projects.opened[identifier]
        source = context.config_dir / 'test_project_config.ini'
        original = source.read_bytes()
        dialog.tabs.setCurrentIndex(1)
        dialog.set_default_commands([dict(command='echo fixture', retry_times=7, expected_segments=[])])
        dialog.interval.setText('无效输入')
        dialog.fields['telnet']['password'].setText('pretest-private-fixture')
        dialog.fields['telnet']['login_success_flag'].setText('>')
        dialog.fields['telnet']['login_after_input_str'].setText('fixture shell')
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            self.app.processEvents()
            self.assertTrue(dialog.grab().save(str(Path(output) / 'pretest-ready.png')))
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.No) as question:
            QTest.mouseClick(dialog.pretest_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: question.called and not dialog.busy)
            summary = question.call_args.args[2]
        self.assertIn('fixture shell', summary)
        self.assertIn('channel_1', summary)
        self.assertIn('channel_7', summary)
        self.assertNotIn('pretest-private-fixture', summary)
        self.assertFalse(dialog._pretest_view[0])

        entered, stopping, release = (threading.Event() for _ in range(3))
        self.addCleanup(release.set)
        requests = []

        def run(request, stop, log):
            requests.append(request)
            entered.set()
            if not stop.wait(6):
                raise AssertionError('pretest never received cooperative stop')
            stopping.set()
            if not release.wait(6):
                raise AssertionError('pretest fixture was not released')
            return PretestResult(total=2, executed=1, unchecked=1, cancelled=True)

        with patch('src.services.qt_pretest.run_pretest', side_effect=run), \
             patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            QTest.mouseClick(dialog.pretest_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: entered.is_set() and dialog.pretest_stop_button.isEnabled())
            self.assertEqual(requests[0].order.items[0].retry_times, 1)
            self.assertEqual(requests[0].order.items[0].command, 'echo fixture')
            self.assertFalse(dialog.tabs.isEnabled())
            self.assertFalse(dialog.close())
            self.wait_for(stopping.is_set)
            self.assertTrue(dialog.isVisible())
            release.set()
            self.wait_for(lambda: dialog._pretest_view[1:3] == ('stopped', False))
            self.assertIn('未执行 1', dialog._pretest_view[3])
            self.assertTrue(dialog.tabs.isEnabled())
            self.assertTrue(dialog.dirty)
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(engine.calls)
            if output:
                self.assertTrue(dialog.grab().save(str(Path(output) / 'pretest-stopped.png')))

    def test_qt_push_trial_uses_confirmed_draft_and_reports_platform_acceptance(self):
        from PySide6.QtWidgets import QLineEdit, QMessageBox
        from qt_execution_fakes import save_push_project_name
        from webhook_fakes import FEISHU
        _, identifier = self._configured_execution()
        workspace = self.controller.adapter._service
        context = workspace.projects.opened[identifier]
        save_push_project_name(workspace, context)
        self.controller.open_configuration()
        self.wait_for(lambda: identifier in self.controller.configuration_editors)
        dialog = self.controller.configuration_editors[identifier]
        paths = [context.config_dir / name for name in ('test_project_config.ini', 'config.ini')]
        original = [path.read_bytes() for path in paths]
        push = dialog.fields['push']
        push['webhook'].setText(FEISHU)
        push['secret'].setText('push-private-fixture')
        push['dingtalk_flag'].setChecked(False)
        push['at_all'].setChecked(True)
        dialog.fields['project_info']['project_name'].setText('未保存的另一项目名')
        dialog.tabs.setCurrentIndex(5)
        self.app.processEvents()
        self.assertEqual(push['webhook'].echoMode(), QLineEdit.EchoMode.Password)
        self.assertEqual(push['secret'].echoMode(), QLineEdit.EchoMode.Password)
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            self.assertTrue(dialog.grab().save(str(Path(output) / 'push-trial-ready.png')))

        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def transport(webhook, secret, text, at_all):
            entered.set()
            if not release.wait(6):
                raise AssertionError('simulated transport was not released')

        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        with patch('src.services.message_push_config_service.send_feishu_text', side_effect=transport) as send, \
                patch('src.services.message_push_config_service.send_text', side_effect=AssertionError('wrong platform')):
            with patch('PySide6.QtWidgets.QMessageBox.question', return_value=no) as question:
                QTest.mouseClick(dialog.push_trial_button, Qt.MouseButton.LeftButton)
                self.wait_for(lambda: question.called and not dialog.busy)
            send.assert_not_called()
            summary = question.call_args.args[2]
            self.assertEqual(question.call_args.args[-1], no)
            self.assertIn('飞书', summary)
            self.assertIn('已保存试发项目', summary)
            self.assertIn('@所有人：开启', summary)
            self.assertNotIn('未保存的另一项目名', summary)
            self.assertNotIn('push-private-fixture', summary)
            self.assertNotIn('demo-token', summary)

            with patch('PySide6.QtWidgets.QMessageBox.question', return_value=yes):
                QTest.mouseClick(dialog.push_trial_button, Qt.MouseButton.LeftButton)
                self.wait_for(lambda: entered.is_set() and dialog._push_trial_active)
            self.assertFalse(dialog.push_trial_button.isEnabled())
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
            self.assertTrue(dialog.isVisible())
            self.assertFalse(dialog.close())
            responded = threading.Event()
            QTimer.singleShot(0, responded.set)
            self.wait_for(responded.is_set)
            self.assertEqual(self.window.projects[0].active_task_count, 0)
            release.set()
            self.wait_for(lambda: '飞书已接受' in dialog.feedback.text() and dialog.push_trial_button.isEnabled())
            send.assert_called_once()
            self.assertIn('项目：已保存试发项目', send.call_args.args[2])
            self.assertTrue(send.call_args.kwargs['at_all'])
        self.assertEqual([path.read_bytes() for path in paths], original)
        self.assertTrue(dialog.dirty)
        dialog.resize(620, 460)
        self.app.processEvents()
        page = dialog.tabs.currentWidget()
        self.assertEqual(page.horizontalScrollBar().maximum(), 0)
        page.ensureWidgetVisible(dialog.push_trial_button)
        self.app.processEvents()
        self.assertTrue(page.viewport().rect().contains(dialog.push_trial_button.mapTo(
            page.viewport(), dialog.push_trial_button.rect().center())))
        if output:
            self.assertTrue(dialog.grab().save(str(Path(output) / 'push-trial-accepted-small.png')))

    def test_qt_version_query_binds_one_channel_and_fills_only_read_only_fields(self):
        from PySide6.QtWidgets import QMessageBox
        from src.services.device_project_info_service import DeviceProjectInfo
        _, identifier = self._configured_execution()
        self.controller.open_configuration()
        self.wait_for(lambda: identifier in self.controller.configuration_editors)
        dialog = self.controller.configuration_editors[identifier]
        context = self.controller.adapter._service.projects.opened[identifier]
        source = context.config_dir / 'test_project_config.ini'
        original = source.read_bytes()
        dialog.tabs.setCurrentIndex(3)
        self.wait_for(lambda: dialog.version_channel.count() == 3)
        self.assertFalse(dialog.version_button.isEnabled())
        self.assertEqual([dialog.version_channel.itemData(i) for i in range(1, 3)], [1, 7])
        dialog.version_channel.setCurrentIndex(dialog.version_channel.findData(7))
        dialog.fields['project_info']['software_version'].setText('基准版本 01')
        dialog.fields['telnet']['login_success_flag'].setText('>')
        dialog.fields['telnet']['login_after_input_str'].setText('fixture shell')
        dialog.fields['telnet']['password'].setText('version-private-fixture')
        dialog.interval.setText('无效输入')
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        self.app.processEvents()
        viewport = dialog.tabs.currentWidget().viewport()
        self.assertTrue(viewport.rect().contains(dialog.version_button.mapTo(viewport, dialog.version_button.rect().center())))
        if output:
            self.assertTrue(dialog.grab().save(str(Path(output) / 'version-query-ready.png')))

        no = QMessageBox.StandardButton.No
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=no) as question:
            QTest.mouseClick(dialog.version_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: question.called and not dialog.busy)
        self.assertEqual(question.call_args.args[-1], no)
        summary = question.call_args.args[2]
        self.assertIn('CH07', summary)
        self.assertIn('fixture shell', summary)
        self.assertNotIn('version-private-fixture', summary)
        self.assertFalse(self.controller.adapter._executions[identifier].jobs)

        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        dialog.fields['telnet']['login_success_flag'].setText('#')
        requests = []

        def query(request, emit):
            requests.append(request)
            entered.set()
            if not release.wait(6):
                raise AssertionError('version query fixture was not released')
            return DeviceProjectInfo('实读版本 07', '内部版本 07', 'Mon Jun 8 10:16:25 UTC 2026')

        with patch('src.services.qt_version_query.query_device_project_info', side_effect=query), \
             patch('PySide6.QtWidgets.QMessageBox.question', return_value=no) as question:
            QTest.mouseClick(dialog.version_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: entered.is_set() and not dialog.tabs.isEnabled())
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
            self.assertTrue(dialog.isVisible())
            self.assertFalse(dialog.close())
            self.assertFalse(self.window.detail.stop_button.isEnabled())
            release.set()
            self.wait_for(lambda: dialog.tabs.isEnabled() and bool(dialog.version_fields[0].text()))
            question.assert_not_called()
        self.assertEqual(requests[0].bind_ip, '192.0.2.7')
        self.assertEqual(requests[0].telnet.password, 'version-private-fixture')
        self.assertEqual([field.text() for field in dialog.version_fields],
            ['实读版本 07', '内部版本 07', 'Mon Jun 8 10:16:25 UTC 2026'])
        self.assertTrue(all(field.isReadOnly() for field in dialog.version_fields))
        self.assertIn('CH07', dialog.version_target.text())
        self.assertEqual(dialog.fields['project_info']['software_version'].text(), '基准版本 01')
        self.assertEqual(source.read_bytes(), original)
        if output:
            self.assertTrue(dialog.grab().save(str(Path(output) / 'version-query-result.png')))
        dialog.resize(620, 460)
        self.app.processEvents()
        page = dialog.tabs.currentWidget()
        self.assertEqual(page.horizontalScrollBar().maximum(), 0)
        page.ensureWidgetVisible(dialog.version_button)
        self.app.processEvents()
        self.assertTrue(page.viewport().rect().contains(dialog.version_button.mapTo(page.viewport(), dialog.version_button.rect().center())))
        if output:
            self.assertTrue(dialog.grab().save(str(Path(output) / 'version-query-small.png')))

    def test_qt_configuration_cancel_and_reload_keep_original_files(self):
        from PySide6.QtWidgets import QMessageBox
        identifier, dialog = self._open_configuration()
        context = self.controller.adapter._service.projects.opened[identifier]
        path = context.config_dir / 'config.ini'
        original = path.read_bytes()
        dialog.fields['push']['secret'].setText('unsaved-private-fixture')
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
            self.assertFalse(dialog.close())
            dialog.request_reload()
        self.assertTrue(dialog.dirty)
        self.assertFalse(dialog.busy)
        self.assertEqual(path.read_bytes(), original)
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            dialog.request_reload()
            self.wait_for(lambda: not dialog.busy and not dialog.dirty)
        self.assertEqual(path.read_bytes(), original)
        self.assertNotEqual(dialog.fields['push']['secret'].text(), 'unsaved-private-fixture')

    def test_qt_configuration_save_remains_bound_when_switching_projects(self):
        from PySide6.QtWidgets import QMessageBox
        from line_check_assistant.test_item_config_store import TestItemConfigStore
        identifier, dialog = self._open_configuration()
        self.controller.submit('create', self.root / 'other-config', '另一个配置项目')
        self.wait_for(lambda: len(self.window.projects) == 2)
        other = self.window.selected_project
        self.assertNotEqual(other, identifier)
        dialog.fields['project_info']['software_version'].setText('only-first-project')
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            dialog.request_save()
            self.wait_for(lambda: not dialog.busy and not dialog.dirty)
        contexts = self.controller.adapter._service.projects.opened
        first = TestItemConfigStore(contexts[identifier].config_dir / 'test_project_config.ini').load()
        second = TestItemConfigStore(contexts[other].config_dir / 'test_project_config.ini').load()
        self.assertEqual(first.project_info.software_version, 'only-first-project')
        self.assertNotEqual(second.project_info.software_version, 'only-first-project')
        self.assertEqual(self.window.selected_project, other)

    def test_qt_configuration_save_busy_close_keeps_event_loop_responsive(self):
        from PySide6.QtWidgets import QMessageBox
        identifier, dialog = self._open_configuration()
        service = self.controller.adapter._executions[identifier].configuration
        original = service._replace
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def delayed(path, value):
            entered.set()
            release.wait(5)
            original(path, value)
        try:
            with patch.object(service, '_replace', side_effect=delayed), \
                 patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
                dialog.fields['runtime']['number_of_tests'].setText('49')
                dialog.request_save()
                self.wait_for(entered.is_set)
                self.assertTrue(dialog.busy)
                self.assertFalse(dialog.close())
                self.window.close()
                self.assertFalse(self.controller.closing)
                ticks = []
                QTimer.singleShot(0, lambda: ticks.append(True))
                self.app.processEvents()
                self.assertTrue(ticks)
                release.set()
                self.wait_for(lambda: not dialog.busy and not dialog.dirty)
        finally:
            release.set()

    def _open_channel_editor(self):
        existing = {project.project_id for project in self.window.projects}
        self.controller.submit('create', self.root / 'channel-config', '通道绑定验证项目')
        self.wait_for(lambda: self.window.selected_project and self.window.selected_project not in existing)
        identifier = self.window.selected_project
        QTest.mouseClick(self.window.detail.channel_edit_button, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: identifier in self.controller.configuration_editors)
        return identifier, self.controller.configuration_editors[identifier]

    def test_qt_channel_editor_preview_cancel_save_and_small_layout(self):
        from PySide6.QtWidgets import QMessageBox
        from line_check_assistant.config_store import ChannelConfigStore
        from src.models.network_adapter import AdapterIdentity
        identifier, dialog = self._open_channel_editor()
        self.wait_for(lambda: not dialog.resources_refreshing)
        detail = self.window.detail
        matrix = detail.channels

        def visible_numbers():
            return tuple(channel.number for channel in matrix.channels)

        original_selection = visible_numbers()
        original_cards = tuple(tile.text() for tile in matrix.tiles)
        self.assertEqual(len(dialog.rows), 16)
        dialog.select_all(False)
        dialog.device_ip.setText('192.168.1.1')
        dialog.power_port.setCurrentText('COM102')
        for index, vlan, port in ((0, 'VLAN116', 'COM16'), (1, 'VLAN115', 'COM15'), (6, 'VLAN122', 'COM22')):
            row = dialog.rows[index]
            row.enabled.setChecked(True)
            row.vlan.setCurrentText(vlan)
            row.port.setCurrentText(port)
        dialog.rows[2].vlan.setCurrentText('VLAN140')
        dialog.rows[2].port.setCurrentText('COM40')
        context = self.controller.adapter._service.projects.opened[identifier]
        path = context.config_dir / 'network_card_ip.ini'
        before = path.read_bytes()
        with patch('src.core.network_adapter.read_adapter_identities', return_value=(AdapterIdentity('VLAN116', 'fixture-guid'),)), \
             patch('src.core.serial_inventory.list_serial_port_names', return_value=['COM16', 'COM102']):
            dialog.request_resources()
            self.wait_for(lambda: not dialog.resources_refreshing)
        self.assertEqual(dialog.rows[2].port.currentText(), 'COM40')
        self.assertEqual(dialog.power_port.currentText(), 'COM102')
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
            QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not dialog.busy)
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(dialog.dirty)
        self.assertEqual(visible_numbers(), original_selection)
        self.assertEqual(tuple(tile.text() for tile in matrix.tiles), original_cards)
        revision = context.identity.revision
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            dialog.request_save()
            self.wait_for(lambda: not dialog.busy and not dialog.dirty and context.identity.revision != revision)
        self.assertEqual([c.section for c in ChannelConfigStore(path).load()], ['channel_1', 'channel_2', 'channel_7'])
        self.wait_for(lambda: visible_numbers() == (1, 2, 7))
        self.assertEqual([tile.text().splitlines()[-1] for tile in matrix.tiles],
                         ['VLAN116 / COM16', 'VLAN115 / COM15', 'VLAN122 / COM22'])
        self.assertEqual(detail.channel_model.channels, matrix.channels)
        self.assertEqual(dialog.rows[2].port.currentText(), 'COM40')
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        for width, height in ((1100, 740), (620, 500)):
            dialog.resize(width, height)
            self.app.processEvents()
            self.assertEqual(dialog.scroll.horizontalScrollBar().maximum(), 0)
            self.assertTrue(dialog.rect().contains(dialog.save_button.mapTo(dialog, QPoint(0, 0))))
            if output:
                self.assertTrue(dialog.grab().save(str(Path(output) / f'channel-editor-{width}.png')))
        dialog.select_all(True)
        self.assertTrue(all(r.enabled.isChecked() for r in dialog.rows))
        dialog.select_all(False)
        self.assertEqual(dialog.rows[2].port.currentText(), 'COM40')
        self.assertEqual(len(ChannelConfigStore(path).load()), 3)
        dialog.rows[0].enabled.setChecked(True)
        dialog.rows[6].enabled.setChecked(True)
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            dialog.request_save()
            self.wait_for(lambda: not dialog.busy and not dialog.dirty and visible_numbers() == (1, 7))
        self.assertEqual([tile.text().splitlines()[-1] for tile in matrix.tiles], ['VLAN116 / COM16', 'VLAN122 / COM22'])
        self.assertEqual(detail.channel_model.channels, matrix.channels)
        self.assertEqual(len(ChannelConfigStore(path).load()), 2)

    def test_qt_reviews_one_persisted_interrupted_job_in_bound_history(self):
        from PySide6.QtWidgets import QMessageBox
        from types import SimpleNamespace
        from src.services.capability_jobs import CapabilityJobs
        from test_qt_log_history import QtLogHistoryTests

        self.controller.submit('create', self.root / 'job-review', '持久任务核实')
        self.wait_for(lambda: len(self.window.projects) == 1)
        project_id = self.window.selected_project
        context = self.controller.adapter._service.projects.opened[project_id]
        identifier = 'job-review-persisted-fixture'
        fixture = CapabilityJobs(context.history / 'ai/business', SimpleNamespace())
        try:
            QtLogHistoryTests.insert_job(fixture, identifier, 1795040380)
            with fixture.db:
                fixture.db.execute('UPDATE jobs SET state=?,payload=? WHERE id=?',
                    ('running', json.dumps(dict(arguments=dict(channel_ids=[1, 7]))), identifier))
        finally:
            fixture.close()
        self.controller.history_action.trigger()
        history = self.controller.log_history
        self.wait_for(lambda: project_id in history.windows and history.windows[project_id].review_action.isEnabled())
        dialog = history.windows[project_id]
        self.assertNotIn(project_id, self.controller.adapter._executions)
        dialog._job_menu(QPoint(4, 4))
        self.wait_for(dialog.job_menu.isVisible)
        from src.services.power_worker_lifetime import ACTIVE
        with patch('src.services.power_worker_lifetime.power_worker_notice', return_value=ACTIVE):
            dialog.review_action.trigger()
            dialog.job_menu.hide()
            self.wait_for(lambda: ACTIVE in dialog.feedback.text())
            self.assertIsNone(dialog.review_dialog)
            output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if output:
                self.assertTrue(dialog.grab().save(str(Path(output) / 'live-power-review-blocked.png')))
        dialog.review_action.trigger()
        self.wait_for(lambda: dialog.review_dialog is not None)
        review = dialog.review_dialog
        self.assertEqual(review.review.job_id, identifier)
        self.assertEqual(review.review.channels, (1, 7))
        self.assertFalse(review.confirm_button.isEnabled())
        review.outcome.setCurrentIndex(review.outcome.findData('succeeded'))
        review.evidence.setPlainText('现场核对模拟结果')
        self.assertTrue(review.confirm_button.isEnabled())
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            self.assertTrue(review.grab().save(str(Path(output) / 'persisted-job-review.png')))
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as confirm:
            QTest.mouseClick(review.confirm_button, Qt.MouseButton.LeftButton)
            self.assertIn(identifier, confirm.call_args.args[2])
            self.assertEqual(confirm.call_args.args[-1], QMessageBox.StandardButton.No)
        jobs = self.controller.adapter._executions[project_id].capabilities.jobs
        self.assertEqual(jobs.runtime_states()[0]['state'], 'unknown')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
                patch.object(jobs, 'start', side_effect=AssertionError('review must not dispatch')):
            QTest.mouseClick(review.confirm_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: dialog.review_dialog is None and 'reconciled' in dialog.logs.text.toPlainText())
        self.assertEqual(dialog.jobs.currentData(), identifier)
        self.assertIn('已完成', dialog.jobs.currentText())
        self.assertFalse(dialog.review_action.isEnabled())
        self.assertNotIn('现场核对模拟结果', dialog.logs.text.toPlainText())
        self.assertEqual(self.window.projects[0].active_task_count, 0)

    def test_qt_history_result_files_open_selected_snapshot_after_workspace_restart(self):
        from types import SimpleNamespace
        from src.services.capability_jobs import CapabilityJobs
        from test_qt_log_history import QtLogHistoryTests

        root = self.root / '批次历史'
        self.controller.submit('create', root, '批次结果项目')
        self.wait_for(lambda: len(self.window.projects) == 1)
        project = self.window.selected_project
        workspace = self.controller.adapter._service
        context = workspace.projects.opened[project]
        jobs = CapabilityJobs(context.history / 'ai/business', SimpleNamespace())
        older, newer = 'old-batch-7', 'new-batch-1'
        paths = {}
        try:
            for order, (job, number) in enumerate(((older, 7), (newer, 1)), 1):
                QtLogHistoryTests.insert_job(jobs, job, 1795040100 + order)
                with jobs.db:
                    jobs.db.execute('UPDATE jobs SET payload=? WHERE id=?',
                        (json.dumps({'arguments': {'channel_ids': [number]}}), job))
                run = workspace.projects.snapshot(context)
                workspace.status.begin(context, job, run, 'aging.start')
                workspace.status.update(job, 'succeeded')
                target = run / f'Auto_power_on_off_tool/test_results/device_{number}'
                target.mkdir(parents=True)
                files = (target / f'device_{number}_command_results_2026112022100{order}.log',
                         target / f'device_{number}_wifi_2026112022100{order}.log')
                for path in files:
                    path.write_text('合成批次结果 ' + job, encoding='utf-8')
                paths[job] = files
        finally:
            jobs.close()
        database = jobs.directory / 'capability_jobs.sqlite3'
        original = database.read_bytes()

        other_root = self.root / '另一个打开的项目'
        self.controller.submit('create', other_root, '另一个打开的项目')
        self.wait_for(lambda: len(self.window.projects) == 2 and self.window.selected_project != project)
        other = self.window.selected_project
        self.window.select_project(project)
        old_adapter = self.controller.adapter
        self.window.close()
        self.wait_for(lambda: old_adapter.closed.is_set() and not self.window.isVisible())
        self.window = MainWindow(demo=False)
        self.controller = WorkspaceController(self.window, Path(__file__).resolve().parents[1],
                                              directory=self.root / 'workspace')
        self.window.resize(1366, 768)
        self.window.show()
        self.wait_for(lambda: self.controller.ready)
        self.assertEqual(self.window.selected_project, project)
        self.assertEqual([p.project_id for p in self.window.projects], [project, other])
        self.assertNotIn(project, self.controller.adapter._executions)
        # The explicit launch-path handler invokes open_project after the ready receipt.
        self.controller.open_project(str(other_root / 'project.linecheck.json'))
        self.wait_for(lambda: self.window.selected_project == other)
        self.assertEqual([p.project_id for p in self.window.projects], [project, other])
        self.window.select_project(project)
        self.controller.history_action.trigger()
        history = self.controller.log_history
        self.wait_for(lambda: project in history.windows and history.windows[project].result_files_action.isEnabled())
        dialog = history.windows[project]
        self.assertEqual(dialog.jobs.currentData(), newer)
        dialog.jobs.setCurrentIndex(dialog.jobs.findData(older))
        self.wait_for(dialog.result_files_action.isEnabled)
        self.assertFalse(dialog.review_action.isEnabled())
        dialog.jobs.customContextMenuRequested.emit(dialog.jobs.rect().center())
        self.wait_for(dialog.job_menu.isVisible)
        dialog.job_menu.hide()
        dialog.result_files_action.trigger()
        self.wait_for(lambda: dialog.result_files_dialog is not None)
        files = dialog.result_files_dialog
        listed = [files.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(files.files.count())]
        self.assertEqual(set(listed), set(paths[older]))
        self.assertTrue(all(files.files.item(i).text().startswith('CH07 · ') for i in range(files.files.count())))
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            self.assertTrue(files.grab().save(str(Path(output) / 'history-batch-result-files.png')))

        with patch('src.services.qt_power_logs.os.startfile') as shell_open:
            files.files.setCurrentRow(listed.index(paths[older][1]))
            QTest.mouseClick(files.open_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: '已打开 CH07' in files.feedback.text())
            shell_open.assert_called_once_with(str(paths[older][1]))
        self.assertEqual(database.read_bytes(), original)
        self.assertEqual(paths[older][0].read_text(encoding='utf-8'), '合成批次结果 ' + older)
        self.assertNotIn(project, self.controller.adapter._executions)
        files.close()
        self.wait_for(lambda: dialog.result_files_dialog is None)
        self.assertTrue(dialog.result_files_action.isEnabled())

    def test_qt_legacy_run_history_reopens_without_a_job_database(self):
        root = self.root / '原工作台项目'
        self.controller.submit('create', root, '旧 GUI 运行历史')
        self.wait_for(lambda: len(self.window.projects) == 1)
        identifier = self.window.selected_project
        context = self.controller.adapter._service.projects.opened[identifier]
        revision = context.identity.revision
        self.controller.close_project()
        self.wait_for(lambda: not self.window.projects)

        # Only the legacy GUI ledger exists in this project. The second row
        # represents an unknown result already reviewed by the local operator.
        original = {}
        for number, state in ((1, 'succeeded'), (2, 'unknown')):
            run_id = f'{number:032x}'
            owner = f'gui:{identifier}:{number + 2:032x}'
            manifest = root / 'runs' / run_id / 'run.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps(dict(project_id=identifier, run_id=run_id, owner=owner, revision=revision,
                operation='_on_start', state=state, created_at=1700000000 + number, started_at=1700000100,
                updated_at=1700000300, finished_at=1700000300, reconciled=state == 'unknown')), encoding='utf-8')
            original[manifest] = manifest.read_bytes()
        database = context.history / 'ai/business/capability_jobs.sqlite3'
        self.assertFalse(database.exists())
        self.controller.submit('open', root)
        self.wait_for(lambda: len(self.window.projects) == 1 and self.window.selected_project == identifier)
        self.controller.history_action.trigger()
        history = self.controller.log_history
        self.wait_for(lambda: identifier in history.windows and not history.windows[identifier].busy)
        dialog = history.windows[identifier]
        self.assertEqual(dialog.jobs.count(), 0)
        from src.services.qt_log_history import read_legacy_runs
        entered = threading.Event()
        release = threading.Event()
        delivered = threading.Event()
        handle = history.handle_result

        def delayed_read(*args, **kwargs):
            entered.set()
            if not release.wait(8):
                raise TimeoutError('history test did not release the read')
            return read_legacy_runs(*args, **kwargs)

        def observe_delivery(result):
            handled = handle(result)
            if result.operation == 'history_legacy_runs':
                delivered.set()
            return handled

        with patch('src.services.qt_log_history.read_legacy_runs', side_effect=delayed_read), \
             patch.object(history, 'handle_result', side_effect=observe_delivery), \
             patch.object(dialog, 'show_legacy', wraps=dialog.show_legacy) as show_legacy:
            try:
                dialog.source.setCurrentIndex(dialog.source.findData('legacy'))
                self.wait_for(entered.is_set)
                self.assertTrue(dialog.source.isEnabled())
                dialog.source.setCurrentIndex(dialog.source.findData('jobs'))
            finally:
                release.set()
            self.wait_for(lambda: delivered.is_set() and not dialog.busy)
            show_legacy.assert_not_called()
            self.assertTrue(dialog.jobs.isVisible())
            self.assertEqual(dialog.jobs.count(), 0)
            self.assertEqual(dialog.legacy_table.rowCount(), 0)
        dialog.source.setCurrentIndex(dialog.source.findData('legacy'))
        self.wait_for(lambda: dialog.legacy_table.isVisible() and dialog.legacy_table.rowCount() == 2 and not dialog.busy)
        self.assertEqual([dialog.legacy_table.item(row, 0).text() for row in range(2)],
                         [f'{2:032x}', f'{1:032x}'])
        self.assertIn('已核实', dialog.legacy_table.item(0, 2).text())
        self.assertIn('成功', dialog.legacy_table.item(1, 2).text())
        self.assertFalse(dialog.older_legacy.isEnabled())
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            self.assertTrue(dialog.grab().save(str(Path(output) / 'legacy-run-history.png')))
        dialog.source.setCurrentIndex(dialog.source.findData('jobs'))
        self.wait_for(lambda: dialog.jobs.isVisible() and not dialog.busy)
        self.assertEqual(dialog.jobs.count(), 0)
        self.assertFalse(database.exists())
        self.assertEqual({path: path.read_bytes() for path in original}, original)

    def test_qt_reopens_original_task_history_and_pages_with_project_isolation(self):
        from types import SimpleNamespace
        from src.services.capability_jobs import CapabilityJobs
        from src.services.qt_log_history import EVENTS_PER_PAGE
        from test_qt_log_history import QtLogHistoryTests

        root = self.root / '持久历史测试'
        self.controller.submit('create', root, '历史验证项目 A')
        self.wait_for(lambda: len(self.window.projects) == 1)
        identifier = self.window.selected_project
        context = self.controller.adapter._service.projects.opened[identifier]
        jobs = CapabilityJobs(context.history / 'ai/business', SimpleNamespace())
        try:
            first_job = '789abcde' * 4
            last_job = '1234abcd' * 4
            QtLogHistoryTests.insert_job(jobs, first_job, 1795040100)
            QtLogHistoryTests.insert_job(jobs, last_job, 1795040380)
            with jobs.db:
                jobs.db.execute('UPDATE jobs SET state=? WHERE id=?', ('running', first_job))
            for index in range(EVENTS_PER_PAGE + 3):
                jobs.event(last_job, 'history', f'{{"channel":7,"message":"persisted-{index:03d}"}}')
            jobs.event(first_job, 'failed', 'older-job-file')
        finally:
            jobs.close()
        source = jobs.directory / 'capability_jobs.sqlite3'
        original = source.read_bytes()
        self.controller.close_project()
        self.wait_for(lambda: not self.window.projects)
        self.controller.submit('open', root)
        self.wait_for(lambda: self.window.selected_project == identifier and len(self.window.projects) == 1)
        self.assertNotIn(identifier, self.controller.adapter._executions)
        self.assertTrue(self.controller.history_action.isEnabled())
        self.controller.history_action.trigger()
        history = self.controller.log_history
        self.wait_for(lambda: identifier in history.windows and history.windows[identifier].older_logs.isEnabled())
        dialog = history.windows[identifier]
        self.assertEqual(dialog.jobs.currentData(), last_job)
        self.assertIn('persisted-062', dialog.logs.text.toPlainText())
        self.assertNotIn('persisted-000', dialog.logs.text.toPlainText())
        dialog.logs.search.setText('PERSISTED-000')
        self.assertEqual(dialog.logs.text.toPlainText(), '')
        self.assertFalse(dialog.older_logs.isEnabled())
        QTest.mouseClick(dialog.newest_logs, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: not dialog.busy and 'persisted-000' in dialog.logs.text.toPlainText())
        self.assertEqual(len(dialog.logs.entries), 1)
        self.assertFalse(dialog.older_logs.isEnabled())
        dialog.logs.search.clear()
        QTest.keyClick(dialog.logs.search, Qt.Key.Key_Return)
        self.wait_for(lambda: not dialog.busy and dialog.older_logs.isEnabled())
        QTest.mouseClick(dialog.older_logs, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: not dialog.busy and 'persisted-000' in dialog.logs.text.toPlainText())
        self.assertFalse(dialog.older_logs.isEnabled())
        self.assertNotIn('persisted-062', dialog.logs.text.toPlainText())
        dialog.logs.scope.setCurrentIndex(dialog.logs.scope.findData(7))
        self.assertIn('历史验证项目 A', dialog.windowTitle())
        self.assertEqual(len(dialog.logs.entries), 3)
        dialog.resize(680, 460)
        self.app.processEvents()
        self.assertTrue(dialog.rect().contains(dialog.close_button.mapTo(dialog, dialog.close_button.rect().bottomRight())))
        self.assertTrue(dialog.logs.rect().contains(dialog.logs.export_button.mapTo(dialog.logs, dialog.logs.export_button.rect().bottomRight())))
        directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if directory:
            self.assertTrue(dialog.grab().save(str(Path(directory) / 'task-history-older-page.png')))

        self.controller.submit('create', self.root / 'history-project-b', '历史验证项目 B')
        self.wait_for(lambda: len(self.window.projects) == 2 and self.window.selected_project != identifier)
        other = self.window.selected_project
        self.controller.history_action.trigger()
        self.wait_for(lambda: other in history.windows and not history.windows[other].busy)
        self.assertEqual(history.windows[other].jobs.count(), 0)
        self.assertEqual(dialog.jobs.currentData(), last_job)
        self.assertFalse((self.root / 'history-project-b/history/ai/business/capability_jobs.sqlite3').exists())
        output = self.root / '历史筛选页.txt'
        with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName', return_value=(str(output), '')):
            QTest.mouseClick(dialog.logs.export_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: output.is_file() and not self.controller._log_export_pending)
        exported = output.read_text(encoding='utf-8-sig')
        self.assertIn(f'[项目={identifier} 任务={last_job} 通道=CH07]', exported)
        self.assertIn('persisted-000', exported)
        self.assertNotIn('persisted-062', exported)
        self.assertNotIn('older-job-file', exported)
        self.assertEqual(source.read_bytes(), original)
        old_index = dialog.jobs.findData(first_job)
        self.assertIn('记录为运行中', dialog.jobs.itemText(old_index))
        dialog.jobs.setCurrentIndex(old_index)
        dialog.logs.scope.setCurrentIndex(dialog.logs.scope.findData('project'))
        self.wait_for(lambda: not dialog.busy and 'older-job-file' in dialog.logs.text.toPlainText())
        self.assertFalse(self.controller.adapter._service.resources.owners)
        self.assertNotIn(identifier, self.controller.adapter._executions)

        # Block A's selected event page and re-open B through the workspace
        # command queue. Both projects contain the same latest Job identifier.
        from src.services.qt_log_history import read_log_history
        other_context = self.controller.adapter._service.projects.opened[other]
        other_jobs = CapabilityJobs(other_context.history / 'ai/business', SimpleNamespace())
        try:
            QtLogHistoryTests.insert_job(other_jobs, last_job, 1795040380)
            other_jobs.event(last_job, 'history', 'only-in-project-b')
        finally:
            other_jobs.close()
        self.window.select_project(identifier)
        entered, release = threading.Event(), threading.Event()

        def delayed_read(context, *args, **kwargs):
            if context.identity.project_id == identifier and not entered.is_set():
                entered.set()
                if not release.wait(15):
                    raise TimeoutError('原窗口的事件页读取未释放')
            return read_log_history(context, *args, **kwargs)

        with patch('src.services.qt_log_history.read_log_history', side_effect=delayed_read):
            with patch.object(dialog, 'show_logs') as display_closed:
                try:
                    dialog.newest_logs.click()
                    self.wait_for(entered.is_set)
                    self.controller.open_project(str(other_context.root))
                    self.wait_for(lambda: self.window.selected_project == other)
                    other_dialog = history.windows[other]
                    other_dialog.newest_jobs.click()
                    self.assertTrue(other_dialog.busy)
                    dialog.close_button.click()
                    self.assertNotIn(identifier, history.windows)
                    self.window.select_project(identifier)
                    self.controller.history_action.trigger()
                    reopened = history.windows[identifier]
                    self.assertIsNot(reopened, dialog)
                finally:
                    release.set()
                self.wait_for(lambda: not history.requests and not reopened.busy and not other_dialog.busy)
                display_closed.assert_not_called()
        for view, project_id in ((reopened, identifier), (other_dialog, other)):
            self.assertEqual(view.jobs.currentData(), last_job)
            self.assertEqual({(row.project_id, row.run_id) for row in view.logs.entries}, {(project_id, last_job)})
        self.assertIn('persisted-062', reopened.logs.text.toPlainText())
        self.assertNotIn('only-in-project-b', reopened.logs.text.toPlainText())
        self.assertIn('only-in-project-b', other_dialog.logs.text.toPlainText())
        self.assertNotIn('persisted-', other_dialog.logs.text.toPlainText())

    def test_qt_log_scopes_and_export_keep_the_exact_job_channel_and_frozen_selection(self):
        from PySide6.QtWidgets import QMessageBox

        engine, identifier = self._configured_execution()
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            self.controller.start_test()
            self.wait_for(engine.started.is_set)
        panel = self.window.logs
        self.wait_for(lambda: panel.scope.findData('run') >= 0 and
                      any(row.channel == 7 and row.run_id for row in panel.entries) and
                      self.window.detail.project.progress == 68)
        job = panel.run_id
        self.assertTrue(any(row.channel == 1 and row.run_id == job for row in panel.entries))
        panel.append_batch((
            LogView('10:02:03', 'WARN', identifier, '模拟旧批次', '历史旧批次的通道', 'earlier-job-id', 1),
            LogView('10:02:03', 'INFO', 'other-project', '其它项目', '同通道编号的其它项目', job, 1),
        ))
        panel.scope.setCurrentIndex(panel.scope.findData('run'))
        self.assertIn('"channel": 7', panel.text.toPlainText())
        self.assertNotIn('历史旧批次', panel.text.toPlainText())
        panel.scope.setCurrentIndex(panel.scope.findData(1))
        panel.level.setCurrentText('INFO')
        panel.search.setText('fixture stage')
        visible = panel.text.toPlainText()
        self.assertIn('"channel": 1', visible)
        self.assertNotIn('"channel": 7', visible)
        self.assertNotIn('其它项目', visible)
        for width in (800, 1000):
            self.window.resize(width, 650)
            self.app.processEvents()
            for control in (panel.scope, panel.export_button):
                self.assertTrue(panel.rect().contains(control.mapTo(panel, control.rect().bottomRight())))
        directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if directory:
            self.assertTrue(self.window.grab().save(str(Path(directory) / 'project-log-channel-scope.png')))
        output = self.root / '已选日志.txt'

        def choose_path(*args, **kwargs):
            self.window.show_dashboard()
            panel.search.clear()
            return str(output), '文本日志 (*.txt)'

        with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName', side_effect=choose_path):
            QTest.mouseClick(panel.export_button, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: output.is_file() and not self.controller._log_export_pending)
        exported = output.read_text(encoding='utf-8-sig')
        self.assertIn(f'[项目={identifier} 任务={job} 通道=CH01]', exported)
        self.assertIn('fixture stage', exported)
        self.assertNotIn('earlier-job-id', exported)
        self.assertNotIn('other-project', exported)
        self.assertNotIn('通道=CH07', exported)
        panel.clear_display()
        self.assertFalse(panel.export_button.isEnabled())
        self.assertEqual(output.read_text(encoding='utf-8-sig'), exported)
        engine.finish.set()
        self.wait_for(lambda: not self.controller.adapter._service.resources.owners)

    def test_qt_toolbar_refresh_updates_another_projects_editor_without_delaying_stop(self):
        from PySide6.QtWidgets import QLabel, QMessageBox, QToolBar
        from src.models.network_adapter import AdapterIdentity

        engine, running = self._configured_execution()
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            self.controller.start_test()
            self.wait_for(engine.started.is_set)
        self.wait_for(lambda: self.window.detail.stop_button.isEnabled())
        _, editor = self._open_channel_editor()
        self.wait_for(lambda: not editor.resources_refreshing)
        editor.power_port.setCurrentText('COM101')
        editor.rows[0].port.setCurrentText('COM777')
        detail = self.window.detail
        old_tiles = tuple(detail.channels.tiles)
        old_summary = [detail.config_layout.itemAt(index).widget() for index in range(detail.config_layout.count())]
        self.window.select_project(running)
        self.assertTrue(any(old_summary))
        self.assertEqual([channel.number for channel in detail.channels.channels], [1, 7])
        self.assertTrue(all(not widget.isVisible() for widget in (*old_tiles, *filter(None, old_summary))))
        action = self.window.resource_refresh_action
        header = self.window.findChild(QToolBar, 'GlobalHeader')
        refresh_button = header.widgetForAction(action)
        self.assertEqual(action.text(), '刷新串口/网卡')
        self.assertTrue(action.isEnabled())
        self.assertTrue(refresh_button.isVisible())
        entered, release = threading.Event(), threading.Event()

        def read_serial():
            entered.set()
            self.assertTrue(release.wait(5))
            raise OSError('fixture unavailable serial inventory')

        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        resources = self.controller.adapter._service.resources
        aliases = dict(resources.aliases)
        with patch('src.core.serial_inventory.list_serial_port_names', side_effect=read_serial) as scan, \
             patch('src.core.network_adapter.read_adapter_identities', return_value=(
                 AdapterIdentity('VLAN103', 'inventory-only-guid'),)):
            QTest.mouseClick(refresh_button, Qt.MouseButton.LeftButton)
            try:
                self.wait_for(entered.is_set)
                self.assertFalse(action.isEnabled())
                self.assertFalse(editor.resources_button.isEnabled())
                self.assertTrue(editor.rows[0].port.isEnabled())
                self.wait_for(lambda: all(tile.width() >= tile.sizeHint().width()
                    and tile.height() >= tile.sizeHint().height() for tile in detail.channels.tiles)
                    and all(text.height() >= text.fontMetrics().height()
                        for text in detail.configuration.findChildren(QLabel) if text.isVisible() and text.text()))
                if output:
                    self.assertTrue(self.window.grab().save(str(Path(output) / 'host-inventory-pending.png')))
                with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
                    QTest.mouseClick(self.window.detail.stop_button, Qt.MouseButton.LeftButton)
                    self.wait_for(engine.stop_observed.is_set)
                self.wait_for(lambda: next(p for p in self.window.projects if p.project_id == running).state == 'stopping')
                self.assertIn('正在读取本机', self.window.statusBar().currentMessage())
                self.assertFalse(release.is_set())
                self.assertTrue(resources.owners)
            finally:
                release.set()
            self.wait_for(lambda: action.isEnabled() and not editor.resources_refreshing)
            scan.assert_called_once()
        self.assertEqual(resources.aliases, aliases)
        self.assertEqual(editor.rows[0].vlan.findText('VLAN103'), 0)
        self.assertEqual(editor.rows[0].port.currentText(), 'COM777')
        self.assertTrue(editor.dirty)
        self.assertIn('串口枚举失败', editor.feedback.text())
        self.assertIn('串口枚举失败', self.window.statusBar().currentMessage())
        if output:
            self.assertTrue(editor.grab().save(str(Path(output) / 'host-inventory-editor-updated.png')))
        engine.release_stop.set()
        self.wait_for(lambda: not resources.owners)

    def test_qt_channel_resources_filter_and_refresh_without_editing_the_draft(self):
        from src.models.network_adapter import AdapterIdentity

        def choices(combo):
            return [combo.itemText(i) for i in range(combo.count())]

        adapters = tuple(AdapterIdentity(alias, f'fixture-{i}') for i, alias in enumerate(
            ('VLAN122', 'VLAN116', 'Wi-Fi', 'VLAN109', 'vlan116', 'VLAN101')))
        with patch('src.core.network_adapter.read_adapter_identities', return_value=adapters), \
             patch('src.core.serial_inventory.list_serial_port_names', return_value=['COM2', 'COM102', 'COM1200']):
            identifier, dialog = self._open_channel_editor()
            self.wait_for(lambda: not dialog.resources_refreshing)
            self.assertFalse(dialog.show_all_resources.isChecked())
            self.assertFalse(dialog.dirty)
            self.assertEqual(choices(dialog.power_port), ['', *(f'COM{i}' for i in range(101, 107))])
            dialog.device_ip.setText('192.168.1.1')
            dialog.power_port.setCurrentIndex(dialog.power_port.findText('COM102'))
            row = dialog.rows[0]
            row.vlan.setCurrentText('VLAN122')
            row.port.setCurrentText('COM1200')
            row.enabled.setChecked(True)
            self.assertEqual(choices(row.vlan), ['VLAN109', 'VLAN116'])
            self.assertEqual(choices(row.port), [f'COM{i}' for i in range(9, 17)])

            directory = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            dialog.resize(620, 500)
            self.wait_for(lambda: all(group.height() >= group.sizeHint().height() and
                row.rect().contains(group.geometry().bottomRight()) for group in row.groups))
            self.assertEqual(dialog.scroll.horizontalScrollBar().maximum(), 0)
            checkbox = dialog.show_all_resources
            self.assertTrue(dialog.rect().contains(checkbox.mapTo(dialog, checkbox.rect().bottomRight())))
            if directory:
                self.assertTrue(dialog.grab().save(str(Path(directory) / 'channel-resources-grouped.png')))

            QTest.mouseClick(dialog.show_all_resources, Qt.MouseButton.LeftButton)
            self.wait_for(lambda: not dialog.resources_refreshing)
            self.assertTrue(dialog.show_all_resources.isChecked())
            self.assertEqual(choices(dialog.power_port), ['', 'COM2', 'COM102', 'COM1200'])
            self.assertEqual(choices(row.vlan), ['VLAN101', 'VLAN109', 'VLAN116', 'VLAN122', 'Wi-Fi'])
            self.assertEqual(choices(row.port), ['COM2', 'COM102', 'COM1200'])
            self.assertTrue(all(choices(r.port) == choices(row.port) for r in dialog.rows))
            if directory:
                self.assertTrue(dialog.grab().save(str(Path(directory) / 'channel-resources-all.png')))

        context = self.controller.adapter._service.projects.opened[identifier]
        path = context.config_dir / 'network_card_ip.ini'
        before, revision = path.read_bytes(), context.identity.revision
        entered, release = threading.Event(), threading.Event()

        def enumerate_ports():
            entered.set()
            self.assertTrue(release.wait(5))
            raise OSError('fixture serial failure')

        with patch('src.core.serial_inventory.list_serial_port_names', side_effect=enumerate_ports), \
             patch('src.core.network_adapter.read_adapter_identities', return_value=()):
            QTest.mouseClick(dialog.resources_button, Qt.MouseButton.LeftButton)
            try:
                self.wait_for(entered.is_set)
                self.assertTrue(dialog.resources_refreshing)
                self.assertFalse(dialog.busy)
                row.port.setCurrentText('COM1600')
                self.assertTrue(row.port.isEnabled())
            finally:
                release.set()
            self.wait_for(lambda: not dialog.resources_refreshing)
        self.assertEqual(choices(row.port), ['COM2', 'COM102', 'COM1200'])
        self.assertEqual(choices(row.vlan), [])
        self.assertIn('串口枚举失败', dialog.feedback.text())
        self.assertTrue(dialog.dirty)
        self.assertTrue(row.enabled.isChecked())
        self.assertEqual(row.vlan.currentText(), 'VLAN122')
        self.assertEqual(row.port.currentText(), 'COM1600')
        QTest.mouseClick(dialog.show_all_resources, Qt.MouseButton.LeftButton)
        dialog.power_port.setCurrentText('COM2')
        self.assertEqual(choices(row.port), [f'COM{i}' for i in range(9, 17)])
        dialog.power_port.setCurrentText('COM1200')
        self.assertEqual(len(choices(row.port)), 48)
        self.assertEqual(dialog.power_port.currentText(), 'COM1200')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(context.identity.revision, revision)

    def test_qt_channel_editor_stays_bound_across_project_switch_and_close(self):
        from PySide6.QtWidgets import QMessageBox
        from line_check_assistant.config_store import ChannelConfigStore
        identifier, dialog = self._open_channel_editor()
        dialog.select_all(False)
        dialog.device_ip.setText('192.168.3.1')
        dialog.rows[0].enabled.setChecked(True)
        dialog.rows[0].vlan.setCurrentText('VLAN118')
        dialog.rows[0].port.setCurrentText('COM18')
        self.controller.submit('create', self.root / 'second-channel-config', '另一个通道项目')
        self.wait_for(lambda: len(self.window.projects) == 2)
        other = self.window.selected_project
        contexts = self.controller.adapter._service.projects.opened
        other_path = contexts[other].config_dir / 'network_card_ip.ini'
        original_other = other_path.read_bytes()
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            dialog.request_save()
            self.wait_for(lambda: not dialog.busy and not dialog.dirty)
        self.assertEqual(other_path.read_bytes(), original_other)
        first = ChannelConfigStore(contexts[identifier].config_dir / 'network_card_ip.ini').load()
        self.assertEqual(first[0].network_card_ip, '192.168.3.118')
        self.assertEqual(self.window.selected_project, other)
        self.assertTrue(dialog.close())
        self.wait_for(lambda: not self.controller.adapter._executions[identifier].editor_open)
        matrix = self.window.detail.channels
        other_labels = [tile.text() for tile in matrix.tiles]
        self.window.select_project(identifier)
        self.assertEqual([c.number for c in matrix.channels if c.selected], [1])
        self.assertIn('已选', matrix.tiles[0].text())
        self.window.select_project(other)
        self.assertEqual([tile.text() for tile in matrix.tiles], other_labels)

    def test_qt_dut_status_height_restores_adjusts_and_saves_each_tab(self):
        from PySide6.QtCore import QRect

        self.controller.submit('create', self.root / 'dut-status-height', 'DUT 状态高度验证')
        self.wait_for(lambda: len(self.window.projects) == 1)
        project = self.window.selected_project
        state = self.root / 'dut-status-height/ui/dut.json'
        state.parent.mkdir(exist_ok=True)
        heights = {'telnet': 3, 'wan': 4, 'wifi_2g': 5, 'wifi_5g': 6, 'voice': 7, 'tr069': 16}
        state.write_text(json.dumps({'current_status_heights': dict(heights, unknown='keep'), 'other': True}), encoding='utf-8')

        # Read the real JSON on the workspace worker after each atomic replace.
        # Polling the destination concurrently can deny the replace on Windows.
        from src.services.qt_window_state import save_window_placement
        saved_state = json.loads(state.read_text(encoding='utf-8'))

        def observe_save(context, window, **preferences):
            nonlocal saved_state
            save_window_placement(context, window, **preferences)
            if window == 'dut' and context.identity.project_id == project:
                saved_state = json.loads(state.read_text(encoding='utf-8'))

        observer = patch('src.services.qt_workspace_adapter.save_window_placement', new=observe_save)
        observer.start()
        self.addCleanup(observer.stop)

        def settle(dialog):
            self.wait_for(lambda: not dialog._status_layout_timer.isActive()
                          and dialog.status_splitter.sizes()[1] ==
                          dialog._status_pixels(dialog.status_heights[dialog.feature]))
            for button in (dialog.query_button, dialog.enable_button, dialog.stop_button, dialog.close_button):
                self.assertTrue(dialog.rect().contains(QRect(button.mapTo(dialog, QPoint(0, 0)), button.size())))

        self.controller.open_dut()
        self.wait_for(lambda: project in self.controller.dut_windows)
        dialog = self.controller.dut_windows[project]
        settle(dialog)
        self.assertEqual(dialog.feature, 'telnet')
        self.assertEqual(dialog.status_heights, heights)
        self.assertEqual(dialog.status_splitter.sizes()[1], dialog._status_pixels(3))
        handle = dialog.status_splitter.handle(1)
        dialog.page_scroll.ensureWidgetVisible(handle)
        start = handle.rect().center()
        target = start + QPoint(0, -2 * dialog.status.fontMetrics().lineSpacing())
        QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(handle, target, delay=20)
        QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=target)
        self.wait_for(lambda: saved_state['current_status_heights']['telnet'] == 5)
        settle(dialog)
        self.assertNotIn('window_size', saved_state)
        for index, feature in enumerate(('wan', 'wifi_2g', 'wifi_5g', 'voice'), 1):
            dialog.tabs.setCurrentIndex(index)
            settle(dialog)
            self.assertEqual(dialog.feature, feature)
            self.assertLessEqual(dialog.status_heights[feature], heights[feature])
        dialog.tabs.setCurrentIndex(0)
        settle(dialog)
        self.assertEqual(dialog.status_heights['telnet'], 5)
        dialog.resize(560, 460)
        dialog.tabs.setCurrentIndex(5)
        settle(dialog)
        self.assertLess(dialog.status_heights['tr069'], 16)
        self.wait_for(lambda: saved_state['current_status_heights']['tr069'] == dialog.status_heights['tr069'])
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
        if output:
            dialog.page_scroll.ensureWidgetVisible(dialog.status)
            QTest.qWait(50)
            self.assertTrue(dialog.grab().save(str(Path(output) / 'dut-status-height-small.png')))
        saved_rows = dict(dialog.status_heights)
        dialog.close()
        self.wait_for(lambda: project not in self.controller.dut_windows)
        self.controller.open_dut()
        self.wait_for(lambda: project in self.controller.dut_windows)
        restored = self.controller.dut_windows[project]
        settle(restored)
        self.assertEqual(restored.status_heights, saved_rows)
        self.assertEqual(saved_state['window_size'], {'width': 560, 'height': 460})
        self.assertEqual(saved_state['current_status_heights']['unknown'], 'keep')
        self.assertTrue(saved_state['other'])

    def test_qt_module_windows_restore_legacy_sizes_and_save_through_project_lifecycle(self):
        from PySide6.QtWidgets import QMessageBox
        from src.ui.window_size_state import save_module_window_size

        engine, project = self._configured_execution()
        directory = self.root / 'power-test'
        state = directory / 'ui/module_windows.json'
        self.controller.close_project()
        self.wait_for(lambda: not self.window.projects)
        sizes = {'test_item_config': (875, 610), 'power_test_channel_history': (782, 422),
                 'pipeline': (862, 515), 'sample_upgrade': (910, 630),
                 'sample_parameter_writer': (922, 635), 'onu_registration': (945, 600)}
        for module, (width, height) in sizes.items():
            self.assertTrue(save_module_window_size(state, module, width, height, default_width=width,
                default_height=height, min_width=1, min_height=1))
        self.controller.submit('open', directory)
        self.wait_for(lambda: self.window.selected_project == project)
        output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')

        def check_and_resize(dialog, module, capture=False):
            self.assertEqual((dialog.width(), dialog.height()), sizes[module], module)
            if output and capture:
                self.assertTrue(dialog.grab().save(str(Path(output) / f'module-size-{module}.png')))
            width, height = sizes[module]
            dialog.resize(width + 23, height + 12)
            return dict(width=dialog.width(), height=dialog.height())

        self.controller.open_configuration()
        self.wait_for(lambda: project in self.controller.configuration_editors)
        configuration = self.controller.configuration_editors[project]
        expected = {'test_item_config': check_and_resize(configuration, 'test_item_config', capture=True)}
        configuration.close()
        self.wait_for(lambda: project not in self.controller.configuration_editors and self.window.projects[0].can_start)
        self.controller.open_configuration()
        self.wait_for(lambda: project in self.controller.configuration_editors)
        configuration = self.controller.configuration_editors[project]
        self.assertEqual((configuration.width(), configuration.height()), tuple(expected['test_item_config'].values()))
        configuration.close()
        self.wait_for(lambda: project not in self.controller.configuration_editors and self.window.projects[0].can_start)

        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            self.controller.start_test()
            self.wait_for(lambda: engine.started.is_set() and self.window.projects[0].power_history_job)
        batch = self.window.projects[0].power_history_job
        history = self.controller.channel_history
        history.open(project, batch, 7)
        self.wait_for(lambda: history.dialog is not None and '暂无' in history.dialog.feedback.text())
        expected['power_test_channel_history'] = check_and_resize(history.dialog, 'power_test_channel_history', capture=True)
        history.dialog.close()
        engine.finish.set()
        self.wait_for(lambda: not self.window.projects[0].active_task_count and self.window.projects[0].can_start)

        tools = (
            ('pipeline', self.controller.open_pipeline, self.controller.pipeline_windows),
            ('sample_upgrade', self.controller.open_upgrade, self.controller.upgrade_windows),
            ('sample_parameter_writer', self.controller.parameter_writer.open, self.controller.parameter_writer.windows),
            ('onu_registration', self.controller.onu_query.open, self.controller.onu_query.windows),
        )
        for module, open_window, windows in tools:
            open_window()
            self.wait_for(lambda: project in windows)
            expected[module] = check_and_resize(windows[project], module, capture=module == 'pipeline')
        self.controller.close_project()
        self.wait_for(lambda: not self.window.projects and all(project not in windows for _, _, windows in tools))
        self.assertEqual(json.loads(state.read_text(encoding='utf-8'))['window_sizes'], expected)

        self.controller.submit('create', self.root / 'module-size-b', '另一项目')
        self.wait_for(lambda: len(self.window.projects) == 1 and self.window.selected_project != project)
        other = self.window.selected_project
        self.controller.open_pipeline()
        self.wait_for(lambda: other in self.controller.pipeline_windows)
        pipeline = self.controller.pipeline_windows[other]
        self.assertEqual((pipeline.width(), pipeline.height()), (570, 355))
        pipeline.resize(710, 430)
        self.window.close()
        self.wait_for(lambda: self.controller.adapter.closed.is_set() and not self.window.isVisible())
        saved = self.root / 'module-size-b/ui/module_windows.json'
        self.assertEqual(json.loads(saved.read_text(encoding='utf-8'))['window_sizes'],
            {'pipeline': {'width': 710, 'height': 430}})
        self.assertEqual(json.loads(state.read_text(encoding='utf-8'))['window_sizes'], expected)

    def test_qt_tool_windows_restore_project_geometry_and_save_on_parent_close(self):
        from PySide6.QtWidgets import QMessageBox
        from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore

        self.controller.submit('create', self.root / 'geometry-a', '布局验证项目 A')
        self.wait_for(lambda: len(self.window.projects) == 1)
        first = self.window.selected_project
        context = self.controller.adapter._service.projects.opened[first]
        ChannelConfigStore(context.config_dir / 'network_card_ip.ini').save([
            ChannelConfig('channel_7', vlan_name='VLAN117', adapter_alias='VLAN117', serial_port='COM17',
                          network_card_ip='192.0.2.117', device_manage_ip='192.0.2.1')])
        revision = context.identity.revision
        self.assertIsNotNone(self.controller.submit('save', first))
        self.wait_for(lambda: context.identity.revision != revision)
        self.controller.submit('create', self.root / 'geometry-b', '布局验证项目 B')
        self.wait_for(lambda: len(self.window.projects) == 2)
        other = self.window.selected_project
        state_a = self.root / 'geometry-a/ui'
        state_b = self.root / 'geometry-b/ui'
        state_a.mkdir(exist_ok=True)
        state_b.mkdir(exist_ok=True)
        old_serial = {'geometry': '1050x680+80+90', 'log_dir': str(self.root)}
        heights = {'telnet': 9, 'wan': 12}
        (state_a / 'serial.json').write_text(json.dumps(old_serial), encoding='utf-8')
        (state_a / 'dut.json').write_text(json.dumps({'window_size': {'width': 940, 'height': 590},
                                                     'current_status_heights': heights}), encoding='utf-8')
        (state_b / 'serial.json').write_text(json.dumps({'qt_geometry': {'width': 790, 'height': 490,
                                                                        'x': 800000, 'y': 800000}}), encoding='utf-8')
        self.window.select_project(first)
        with patch('serial.Serial', side_effect=AssertionError('layout must not open a port')), \
                patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            self.controller.open_serial()
            self.controller.open_dut()
            self.wait_for(lambda: first in self.controller.serial_windows and first in self.controller.dut_windows)
            serial = self.controller.serial_windows[first]
            dut = self.controller.dut_windows[first]
            bounds = serial.screen().availableGeometry()
            full_screen = serial.screen().geometry()
            if bounds.width() > 1080:
                self.assertEqual(serial.width(), 1050)
            if bounds.width() > 970:
                self.assertEqual(dut.width(), 940)
            if full_screen.left() + 80 + serial.frameGeometry().width() <= bounds.right() + 1:
                self.assertEqual(serial.x(), full_screen.left() + 80)
            if full_screen.top() + 90 + serial.frameGeometry().height() <= bounds.bottom() + 1:
                self.assertEqual(serial.y(), full_screen.top() + 90)
            self.assertLessEqual(serial.width(), bounds.width())
            self.assertLessEqual(serial.height(), bounds.height())
            self.assertEqual(serial.path.text(), str(self.root))
            self.assertEqual(serial.tabs.tabText(0), 'vlan117 / COM17')

            serial.resize(762, 502)
            serial.move(bounds.left() + 66, bounds.top() + 78)
            before = (serial.width(), serial.height(), serial.x(), serial.y())
            serial.close()
            self.wait_for(lambda: first not in self.controller.serial_windows)
            self.controller.open_serial()
            self.wait_for(lambda: first in self.controller.serial_windows)
            serial = self.controller.serial_windows[first]
            self.assertEqual((serial.width(), serial.height(), serial.x(), serial.y()), before)
            self.assertEqual({key: json.loads((state_a / 'serial.json').read_text(encoding='utf-8'))[key]
                              for key in old_serial}, old_serial)

            dut.resize(824, 503)
            self.wait_for(lambda: not dut._status_layout_timer.isActive()
                          and dut.status_splitter.sizes()[1] ==
                          dut._status_pixels(dut.status_heights['telnet']))
            effective_height = dut.status_heights['telnet']
            self.assertGreaterEqual(effective_height, 2)
            self.assertLessEqual(effective_height, heights['telnet'])
            output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
            if output:
                QTest.qWait(60)
                self.assertTrue(serial.grab().save(str(Path(output) / 'serial-project-placement.png')))
                self.assertTrue(dut.grab().save(str(Path(output) / 'dut-project-placement.png')))
            self.controller.close_project()
            self.wait_for(lambda: first not in self.controller.serial_windows and first not in self.controller.dut_windows)
            saved_dut = json.loads((state_a / 'dut.json').read_text(encoding='utf-8'))
            self.assertEqual(saved_dut, {
                'window_size': {'width': 824, 'height': 503},
                'current_status_heights': dict(heights, telnet=effective_height),
            })
            self.window.select_project(other)
            self.controller.open_serial()
            self.wait_for(lambda: other in self.controller.serial_windows)
            serial = self.controller.serial_windows[other]
            self.assertTrue(serial.screen().availableGeometry().contains(serial.frameGeometry()))
            self.assertEqual((serial.width(), serial.height()), (790, 490))
            serial.resize(815, 505)
            exit_size = (serial.width(), serial.height(), serial.x(), serial.y())
            self.window.close()
            self.wait_for(lambda: self.controller.adapter.closed.is_set() and not self.window.isVisible())
        position = json.loads((state_b / 'serial.json').read_text(encoding='utf-8'))['qt_geometry']
        self.assertEqual(tuple(position[key] for key in ('width', 'height', 'x', 'y')), exit_size)

    def test_qt_channel_candidate_rename_confirms_and_keeps_unsaved_fields(self):
        from PySide6.QtWidgets import QMessageBox
        from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
        from src.models.network_adapter import AdapterIdentity
        from src.services.qt_host_inventory import HostInventoryReading

        old, new, guid = '模拟测试接口', 'VLAN137', 'qt-native-rename-fixture-guid'
        self.controller.submit('create', self.root / 'native-rename', '网卡改名验证项目')
        self.wait_for(lambda: len(self.window.projects) == 1)
        project = self.window.projects[0]
        self.controller.submit('create', self.root / 'native-rename-other', '共享网卡项目')
        self.wait_for(lambda: len(self.window.projects) == 2)
        other = self.window.selected_project
        workspace = self.controller.adapter._service
        path = workspace.projects.opened[project.project_id].config_dir / 'network_card_ip.ini'
        store = ChannelConfigStore(path)
        store.save([ChannelConfig('channel_1', vlan_name='VLAN131', device_manage_ip='192.168.7.1')])
        other_store = ChannelConfigStore(workspace.projects.opened[other].config_dir / 'network_card_ip.ini')
        other_store.save([ChannelConfig('channel_7', vlan_name=old, adapter_alias=old,
            serial_port='COM47', device_manage_ip='192.168.9.1')])
        self.window.select_project(project.project_id)
        adapters = [AdapterIdentity(old, guid, 'Up')]
        inventory = HostInventoryReading(('COM31',), tuple(adapters))
        with patch('src.services.qt_workspace_adapter.read_host_inventory', return_value=inventory):
            self.controller.open_channels()
            self.wait_for(lambda: project.project_id in self.controller.configuration_editors)
            dialog = self.controller.configuration_editors[project.project_id]
            self.wait_for(lambda: not dialog.resources_refreshing and old in dialog.adapters)
        self.assertEqual(dialog.rows[0].vlan.currentText(), 'VLAN131')
        dialog.device_ip.setText('192.168.8.1')
        rename = self.controller.adapter._adapter_rename.rename_service
        def change(source, destination):
            self.assertEqual(source, old)
            adapters[:] = [AdapterIdentity(destination, guid, 'Up')]
        def choose():
            combo = dialog.rows[0].vlan
            self.assertNotEqual(combo.findText(old), -1)
            combo.showPopup()
            index = combo.model().index(combo.findText(old), 0)
            combo.view().setCurrentIndex(index)
            QTest.keyClick(combo.view(), Qt.Key.Key_Return)
        with patch.object(rename, 'availability', return_value=''), \
                patch.object(rename, 'reader', side_effect=lambda: tuple(adapters)), \
                patch.object(rename, 'renamer', side_effect=change) as dispatch, \
                patch('PySide6.QtWidgets.QInputDialog.getText', return_value=(new, True)) as ask_name:
            with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.No) as question:
                choose()
                ask_name.assert_called_once()
                self.wait_for(lambda: '已取消改名' in dialog.feedback.text())
                self.assertIn(guid, question.call_args.args[2])
                self.assertIn('共享网卡项目 · channel_7', question.call_args.args[2])
                self.assertEqual(question.call_args.args[-1], QMessageBox.StandardButton.No)
            dispatch.assert_not_called()
            self.assertEqual(dialog.rows[0].vlan.currentText(), 'VLAN131')
            self.assertEqual(store.load()[0].vlan_name, 'VLAN131')
            self.assertEqual(other_store.load()[0].vlan_name, old)
            with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
                choose()
                self.wait_for(lambda: not dialog.busy and '回读确认成功' in dialog.feedback.text())
                self.assertEqual(dialog.rows[0].vlan.currentText(), new)
                self.assertEqual(dialog.device_ip.text(), '192.168.8.1')
                self.assertTrue(dialog.dirty)
                self.assertEqual(dialog.rows[0].port.currentText(), 'COM31')
                saved = store.load()[0]
                self.assertEqual((saved.vlan_name, saved.device_manage_ip, saved.network_card_ip), (new, '192.168.7.1', '192.168.7.137'))
                shared = other_store.load()[0]
                self.assertEqual((shared.vlan_name, shared.adapter_alias, shared.serial_port, shared.network_card_ip),
                                 (new, new, 'COM47', '192.168.9.137'))
                output = os.environ.get('DUTPILOT_QT_CAPTURE_DIRECTORY')
                if output:
                    QTest.qWait(60)
                    self.assertTrue(dialog.grab().save(str(Path(output) / 'channel-adapter-renamed.png')))
                dialog.close()
            dispatch.assert_called_once_with(old, new)

    def test_qt_saved_channel_selection_drives_original_job_targets(self):
        from PySide6.QtWidgets import QMessageBox
        from line_check_assistant.config_store import ChannelConfigStore
        engine, identifier = self._configured_execution()
        self.controller.open_channels()
        self.wait_for(lambda: identifier in self.controller.configuration_editors)
        dialog = self.controller.configuration_editors[identifier]
        dialog.select_all(False)
        dialog.rows[0].enabled.setChecked(True)
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            dialog.request_save()
            self.wait_for(lambda: not dialog.busy and not dialog.dirty)
            dialog.close()
            self.wait_for(lambda: self.window.detail.start_button.isEnabled())
            QTest.mouseClick(self.window.detail.start_button, Qt.MouseButton.LeftButton)
            self.wait_for(engine.started.is_set)
            self.assertEqual([c.section for c in engine.calls[0][0].enabled_channels], ['channel_1'])
            self.wait_for(lambda: self.window.projects[0].progress == 68)
            self.window.detail.set_channel_mode(1)
            model = self.window.detail.channel_model
            matrix = self.window.detail.channels
            self.assertEqual(model.rowCount(), 1)
            self.assertEqual(matrix.tiles[0].text().splitlines()[-1], 'VLAN101 / COM1')
            self.assertEqual((model.index(0, 3).data(), model.index(0, 4).data()), ('VLAN101', 'COM1'))
            self.assertFalse(self.window.detail.channel_edit_button.isEnabled())
            engine.finish.set()
            self.wait_for(lambda: self.window.detail.channel_edit_button.isEnabled())
            self.window.detail.set_channel_mode(0)
            self.assertEqual(matrix.channels[0].state, 'success')
            self.assertTrue(matrix.channels[0].selected)
            self.controller.open_channels()
            self.wait_for(lambda: identifier in self.controller.configuration_editors)
            dialog = self.controller.configuration_editors[identifier]
            dialog.rows[0].enabled.setChecked(False)
            dialog.rows[6].enabled.setChecked(True)
            dialog.rows[6].vlan.setCurrentText('VLAN107')
            dialog.rows[6].port.setCurrentText('COM7')
            dialog.request_save()
            self.wait_for(lambda: not dialog.busy and not dialog.dirty
                          and [channel.number for channel in matrix.channels] == [7])
            context = self.controller.adapter._service.projects.opened[identifier]
            saved = ChannelConfigStore(context.config_dir / 'network_card_ip.ini').load()
            self.assertEqual([(c.section, c.vlan_name, c.serial_port) for c in saved], [('channel_7', 'VLAN107', 'COM7')])
            finished_channel = self.window.projects[0].channels[0]
            self.assertEqual((finished_channel.state, finished_channel.cycle), ('success', 68))
            self.assertEqual((finished_channel.vlan, finished_channel.port), ('VLAN101', 'COM1'))
            self.assertEqual(matrix.tiles[0].text().splitlines(), ['CH07  未知', '已选'])
            self.assertEqual(model.channels, matrix.channels)
            self.assertEqual((model.index(0, 3).data(), model.index(0, 4).data()), ('未配置', '未配置'))
            self.assertEqual(self.window.projects[0].channel_snapshot_label, '本次任务配置快照')
