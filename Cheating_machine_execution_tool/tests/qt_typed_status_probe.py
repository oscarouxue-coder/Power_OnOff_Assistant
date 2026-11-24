"""Isolated native rendering of per-DUT observations from both test types."""
from types import SimpleNamespace
import unittest

from qt_test_guard import install_qt_test_scope
from src.ui.qt.test_type_panel import TestTypePanel
from src.ui.qt.service_aging_history_dialog import AgingHistoryDialog


class TypedStatusTests(unittest.TestCase):
    def test_qt_dut_presence_displays_explicit_device_evidence_and_history(self):
        scope = install_qt_test_scope(self)
        panel = TestTypePanel()
        self.addCleanup(panel.close)
        panel.show()
        stamp = 1750000000
        observed = dict(dut_id='DUT-a', label='样机甲', subscribed=True, state='online',
                        last_observation=stamp, last_heartbeat=stamp, last_boot_id='boot-A', last_boot_at=stamp,
                        last_uptime_seconds=0, last_uptime_at=stamp, reboot_count=0, last_reboot_at=None,
                        detail='现场确认启动')
        empty = dict(observed, dut_id='DUT-b', label='样机乙', subscribed=False, state='unknown',
                     last_observation=None, last_heartbeat=None, last_boot_id=None, last_boot_at=None,
                     last_uptime_seconds=None, last_uptime_at=None, reboot_count=None, detail='')
        project = SimpleNamespace(project_id='project-A', name='挂测', project_type='service_aging',
                                  test_overview={'dut_presence': [observed, empty], 'rows': []})
        panel.set_project(project)
        scope.app.processEvents()
        self.assertTrue(panel.presence.isVisible())
        self.assertEqual([panel.presence.item(0, c).text() for c in (1, 4, 5, 6)], ['在线', 'boot-A', '0 秒', '0'])
        self.assertEqual([panel.presence.item(1, c).text() for c in (1, 3, 5, 6)], ['未接入', '—', '—', '—'])
        self.assertEqual(panel.table.rowCount(), 0)
        for state, caption in [('offline', '离线'), ('unknown', '未知')]:
            project.test_overview = dict(rows=[], dut_presence=[dict(observed, state=state, last_observation=stamp + 12)])
            panel.set_project(project)
            self.assertEqual(panel.presence.item(0, 1).text(), caption)
            self.assertIn(panel.presence.item(0, 3).text(), panel.presence.item(0, 5).toolTip())
        history = AgingHistoryDialog(panel, project)
        self.addCleanup(history.close)
        sample = dict(at=stamp, dut_id='DUT-a', label='样机甲', collector='dut_presence', kind='sample',
                      outcome='healthy', operator='', evidence='启动标识回读', source='jsonl', event_id='evt-1',
                      received_at=stamp + 2, boot_id='boot-A', uptime_seconds=0)
        history.set_page(dict(rows=[sample], next_before=None))
        history.table.selectRow(0)
        self.assertEqual(history.table.item(0, 4).text(), '在线')
        self.assertIn('启动标识：boot-A', history.evidence.toPlainText())
        self.assertIn('上报开机时长：0 秒', history.evidence.toPlainText())
        panel.set_project(SimpleNamespace(project_id='project-B', project_type='power_cycle', test_overview={},
                                          progress=None, run_id=''))
        self.assertTrue(panel.presence.isHidden())
        self.assertEqual(panel.presence.rowCount(), 0)

    def test_qt_switch_preserves_reported_progress_and_separates_health_sources(self):
        scope = install_qt_test_scope(self)
        panel = TestTypePanel()
        self.addCleanup(panel.close)
        panel.show()
        project = SimpleNamespace(project_id='aging-A', project_type='service_aging', test_overview={})
        panel.set_project(project)
        self.assertIn('尚无运行', panel.title.text())
        self.assertNotIn('时长', panel.title.text())
        healthy = dict(dut_id='a', label='样机 A', collector='lan_ping', source='icmp', state='healthy',
                       checks=12, success_rate=1, last_success=1750000000, consecutive_failures=0,
                       abnormal_seconds=0, observed_seconds=330, last_heartbeat=1750000000,
                       recoveries=0, detail='收到应答', packet_loss=0)
        unknown = dict(healthy, dut_id='b', label='样机 B', state='unknown', success_rate=None,
                       checks=0, last_heartbeat=None, last_success=None, packet_loss=None, detail='等待首次观测')
        project.test_overview = dict(job_id='batch', state='running', target_hours=168, elapsed_seconds=3600,
                                     rows=[healthy, unknown])
        panel.set_project(project)
        scope.app.processEvents()
        self.assertEqual(panel.cards['lan_ping'].badge.text(), '未知')
        self.assertIn('正常 1 台', panel.cards['lan_ping'].detail.text())
        self.assertTrue(panel.ring.isHidden())
        self.assertEqual(panel.table.item(1, 5).text(), '—')
        selected_cell = panel.table.item(1, 5)
        panel.table.selectRow(1)
        project.test_overview = dict(project.test_overview, elapsed_seconds=3660)
        panel.set_project(project)
        self.assertIn('监测时长 1时1分', panel.title.text())
        self.assertIs(panel.table.item(1, 5), selected_cell)
        self.assertEqual(panel.table.currentRow(), 1)
        self.assertTrue(panel.record_button.isEnabled())
        project.test_overview = dict(project.test_overview, rows=[
            healthy, dict(unknown, state='healthy', checks=1, success_rate=1),
        ])
        panel.set_project(project)
        self.assertEqual(panel.table.item(1, 5).text(), '100.0%')
        self.assertEqual(panel.table.currentRow(), 1)
        self.assertEqual(panel.cards['lan_ping'].badge.text(), '正常')
        project.test_overview = dict(project.test_overview, feed_path='X:/架台/history/aging-input/batch.jsonl',
                                     rows=[dict(unknown, collector='voice', source='jsonl')])
        panel.set_project(project)
        self.assertEqual(panel.table.item(0, 3).text(), '现场采集')
        self.assertTrue(panel.feed_path.isReadOnly())
        self.assertTrue(panel.feed_location.isVisible())
        self.assertEqual(panel.feed_path.text(), project.test_overview['feed_path'])
        panel.table.selectRow(0)
        self.assertTrue(panel.record_button.isEnabled())
        power_row = dict(dut_id='a', label='样机 A', channel=1, stage='完成', cycle=5, completed=5,
                         success=5, failure=0, retries=1, duration=64.5)
        power = SimpleNamespace(project_id='power-B', project_type='power_cycle', progress=30, run_id='job-B',
                                test_overview=dict(target=10, rows=[power_row, dict(power_row, dut_id='b', completed=3)]))
        panel.set_project(power)
        self.assertEqual(panel.ring.value, 30)
        self.assertTrue(panel.health_cards.isHidden())
        self.assertTrue(panel.feed_location.isHidden())
        self.assertEqual(panel.feed_path.text(), '')
        self.assertFalse(panel.record_button.isEnabled())
        self.assertEqual(panel.table.item(0, 7).text(), '1')
        self.assertEqual(panel.table.item(0, 8).text(), '64.5 秒')
