"""Behavioral regression tests; no hardware or full application startup."""
import gc
import queue
import threading
import time
import unittest
import weakref
import subprocess
import sys
from types import SimpleNamespace

from src.utils.bounded_mailbox import BoundedMailbox
from src.services.pipeline_runtime import PipelineChannel, PipelineDispatcher, PipelineUiError
from src.models.serial_delivery import SerialDelivery


class MailboxTests(unittest.TestCase):
    def test_fifo_capacity_and_drops(self):
        box = BoundedMailbox(2)
        box.put_nowait('one')
        box.put_nowait('two')
        with self.assertRaises(queue.Full):
            box.put_nowait('three')
        self.assertEqual(box.dropped, 1)
        self.assertEqual([box.get_nowait(), box.get_nowait()], ['one', 'two'])
        self.assertTrue(box.empty())

    def test_consumer_and_producer_never_wait_for_busy_mutex(self):
        # A regression to blocking acquisition must only hang a timed child.
        code = """import queue,time
from src.utils.bounded_mailbox import BoundedMailbox
box=BoundedMailbox(2)
box._lock.acquire()
start=time.monotonic()
try:
    box.get_nowait()
except queue.Empty:
    pass
else:
    raise AssertionError('busy get must yield')
try:
    box.put_nowait('busy')
except queue.Full:
    pass
else:
    raise AssertionError('busy put must drop')
assert time.monotonic()-start < .1
"""
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code], capture_output=True,
                                text=True, encoding='utf-8', timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_receiver_invalidates_and_does_not_own_window(self):
        box = BoundedMailbox(8)
        owner = SimpleNamespace()  # receiver accepts no owner argument
        delivery = SerialDelivery('vlan101', box)
        event = SimpleNamespace(text='old')
        delivery(event)
        delivery.invalidate()
        delivery(event)
        self.assertEqual(box.qsize(), 1)
        self.assertIs(box.get_nowait()[2], delivery)
        self.assertNotIn(owner, vars(delivery).values())

    def test_retired_poll_cannot_register_in_reopened_window(self):
        from pathlib import Path
        from unittest.mock import Mock
        from src.ui.serial_terminal import SerialTerminalWindow
        from src.ui.tk_lifecycle import TkScope
        terminal = SerialTerminalWindow(SimpleNamespace(), Mock(), Path('.'))
        terminal.window = Mock()
        previous, current = terminal._scope, TkScope()
        terminal._scope = current
        terminal._poll(previous)
        terminal.window.after.assert_not_called()
        terminal._scope = previous
        terminal._process_closes = Mock()
        terminal._active_vlan = Mock(side_effect=lambda: setattr(terminal, '_scope', current))
        terminal._poll(previous)
        terminal.window.after.assert_not_called()
        # Also protect a poll already in flight if close/reopen changes scope.
        terminal._scope = previous
        terminal._process_closes = Mock(side_effect=lambda: setattr(terminal, '_scope', current))
        terminal._poll(previous)
        terminal.window.after.assert_not_called()


class PipelineRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.channel = PipelineChannel(dispatch_timeout=.05)
        self.dispatcher = PipelineDispatcher(self.channel)
        self.addCleanup(self.dispatcher.dispose)
        self.run = self.channel.new_run()

    def submit(self, code='test', args=(), cleanup=False):
        result = []
        def worker():
            try:
                result.append(self.channel.invoke(self.run, code, args, cleanup=cleanup))
            except Exception as exc:
                result.append(exc)
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        limit = time.monotonic() + 1
        while self.channel.requests.empty() and thread.is_alive() and time.monotonic() < limit:
            time.sleep(.001)
        self.addCleanup(lambda: (self.channel.close(), thread.join(1)))
        return thread, result

    def test_expired_request_never_executes_later(self):
        calls = []
        self.dispatcher.handlers['test'] = lambda request: calls.append(True)
        thread, result = self.submit()
        thread.join(1)
        self.assertIsInstance(result[0], PipelineUiError)
        self.dispatcher.poll()
        self.assertEqual(calls, [])

    def test_cancel_pending_and_close_release_waiters(self):
        for close in (False, True):
            channel = PipelineChannel()
            run = channel.new_run()
            errors = []
            def worker():
                try:
                    channel.invoke(run, 'never')
                except PipelineUiError as exc:
                    errors.append(str(exc))
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            if close:
                channel.close()
            else:
                run.cancel()
            thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 1)

    def test_cancel_during_confirmation_prevents_admission(self):
        entered = threading.Event()
        admitted = []
        def handler(request):
            entered.set()
            self.run.cancel()
            admitted.append(request.admit())
            return False
        self.dispatcher.handlers['test'] = handler
        thread, result = self.submit()
        self.dispatcher.poll()
        thread.join(1)
        self.assertTrue(entered.is_set())
        self.assertEqual(admitted, [False])
        self.assertIsInstance(result[0], PipelineUiError)

    def test_admitted_action_reports_cancellation_without_replay(self):
        calls = []
        def handler(request):
            calls.append(request.admit())
            self.run.cancel()
            return True
        self.dispatcher.handlers['test'] = handler
        thread, result = self.submit()
        self.dispatcher.poll()
        thread.join(1)
        self.assertEqual(calls, [True])
        self.assertIsInstance(result[0], PipelineUiError)
        self.assertIn('已准入', str(result[0]))
        self.dispatcher.poll()
        self.assertEqual(len(calls), 1)

    def test_error_transfer_does_not_keep_ui_traceback(self):
        class UiOwner:
            pass
        owner = UiOwner()
        reference = weakref.ref(owner)
        def handler(request):
            local_ui = owner
            raise ValueError('expected failure')
        self.dispatcher.handlers['test'] = handler
        thread, result = self.submit()
        self.dispatcher.poll()
        thread.join(1)
        self.assertIn('ValueError: expected failure', str(result[0]))
        self.dispatcher.handlers.clear()
        owner = None
        handler = None
        gc.collect()
        self.assertIsNone(reference())

    def test_stop_keeps_cleanup_notification_deliverable(self):
        self.run.cancel()
        calls = []
        self.dispatcher.handlers['test'] = lambda request: calls.append('finished')
        thread, result = self.submit(cleanup=True)
        self.dispatcher.poll()
        thread.join(1)
        self.assertEqual(calls, ['finished'])
        self.assertEqual(result, [None])

    def test_main_thread_query_executes_inline_without_queuing(self):
        owner = threading.get_ident()
        calls = []
        self.dispatcher.handlers['query'] = lambda request: calls.append(threading.get_ident()) or 42
        self.assertEqual(self.channel.invoke(self.run, 'query'), 42)
        self.assertEqual(calls, [owner])
        self.assertTrue(self.channel.requests.empty())

    def test_discarded_acquisition_releases_resource_after_running_cancel(self):
        released = []
        class Resource:
            def discard(self):
                released.append(True)
        def acquire(request):
            self.assertTrue(request.admit())
            self.run.cancel()
            return Resource()
        self.dispatcher.handlers['test'] = acquire
        thread, result = self.submit()
        self.dispatcher.poll()
        thread.join(1)
        self.assertEqual(released, [True])
        self.assertIsInstance(result[0], PipelineUiError)

    def test_actual_upgrade_entry_rejects_cancel_after_confirmation(self):
        from line_check_assistant.app import LineCheckAssistant
        request = self.channel.post(self.run, 'test')
        self.assertTrue(request.start())
        self.dispatcher.current = request
        self.run.cancel()
        messages = []
        app = SimpleNamespace(_pipeline_ui=SimpleNamespace(dispatcher=self.dispatcher), _log=messages.append)
        self.assertFalse(LineCheckAssistant._launch_upgrade_run(app, lambda: self.fail('must not start'), ()))
        self.assertNotIn('_sample_upgrade_run', app.__dict__)
        self.assertTrue(any('未启动设备操作' in line for line in messages))
        self.dispatcher.current = None

    def test_build_context_rejects_worker_before_reading_any_tk_input(self):
        from line_check_assistant.pipeline_window import PipelineWindow
        from src.ui.tk_lifecycle import TkScope
        touched, errors = [], []
        owner = SimpleNamespace(_scope=TkScope(), app=SimpleNamespace(
            _current_sample_upgrade_settings=lambda: touched.append(True)))
        def worker():
            try:
                PipelineWindow._build_context(owner)
            except RuntimeError as exc:
                errors.append(str(exc))
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(touched, [])
        self.assertEqual(len(errors), 1)

    def test_main_exit_polls_serial_completion_without_join_or_destroying_early(self):
        from unittest.mock import Mock
        from line_check_assistant.app import LineCheckAssistant
        done = threading.Event()
        ticket = SimpleNamespace(done=done, error='')
        manager = Mock()
        manager.shutdown_all.return_value = (ticket,)
        app = SimpleNamespace(serial_session_manager=manager, after=Mock(), _on_app_close=Mock(), destroy=Mock())
        LineCheckAssistant._on_app_close(app)
        manager.shutdown_all.assert_called_once_with(wait=False)
        app.destroy.assert_not_called()
        self.assertTrue(app._app_closing)
        self.assertFalse(LineCheckAssistant._pipeline_admit_action(app))
        done.set()
        LineCheckAssistant._on_app_close(app)
        manager.shutdown_all.assert_called_once()
        app.destroy.assert_called_once()

    def test_main_exit_keeps_gui_alive_for_existing_background_task(self):
        from unittest.mock import Mock
        from line_check_assistant.app import LineCheckAssistant
        manager = Mock()
        app = SimpleNamespace(serial_session_manager=manager, running=True, after=Mock(),
                              _on_app_close=Mock(), destroy=Mock())
        LineCheckAssistant._on_app_close(app)
        manager.shutdown_all.assert_not_called()
        app.destroy.assert_not_called()
        app.after.assert_called_once_with(100, app._on_app_close)

    def test_exit_checks_actual_thread_after_running_flag_clears(self):
        from unittest.mock import Mock
        from line_check_assistant.app import LineCheckAssistant
        waiting = threading.Event()
        app = SimpleNamespace(serial_session_manager=Mock(), running=False, after=Mock(),
                              _on_app_close=Mock(), destroy=Mock())
        worker = threading.Thread(target=lambda: waiting.wait(2), daemon=True)
        self.addCleanup(waiting.set)
        LineCheckAssistant._start_tracked_worker(app, worker)
        LineCheckAssistant._on_app_close(app)
        app.destroy.assert_not_called()
        app.serial_session_manager.shutdown_all.assert_not_called()
        waiting.set()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        app.serial_session_manager.shutdown_all.return_value = ()
        LineCheckAssistant._on_app_close(app)
        app.destroy.assert_called_once()

    def test_closed_subscriber_can_reenter_close_without_hanging(self):
        code = """from src.core.serial_transport import PySerialSession
from src.models import SerialSettings
session=PySerialSession(SerialSettings('SIM77'))
seen=[]
def callback(event):
    if event.direction=='STATE':
        session.close()
        seen.append(event.text)
session.subscribe(callback)
session.close()
assert seen==['串口已关闭']
"""
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code],capture_output=True,
                                text=True,encoding='utf-8',timeout=3)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_cancelled_pipeline_waits_for_admitted_subtask_cleanup_before_restart(self):
        from unittest.mock import Mock
        from src.ui.pipeline_ui import PipelineUiController
        app = SimpleNamespace(_pipeline_subtask_events={}, _pipeline_subtask_results={})
        app._begin_pipeline_subtask = lambda code: app._pipeline_subtask_events.setdefault(code, threading.Event())
        app._start_pipeline_sample_upgrade_on_ui = lambda skip: True
        controller = PipelineUiController(app)
        self.addCleanup(controller.dispatcher.dispose)
        run = controller.channel.new_run()
        window = SimpleNamespace(_closed=False, _on_pipeline_complete=Mock())
        thread = Mock(is_alive=Mock(return_value=False))
        controller.register(window, run, thread)
        controller._start_subtask(SimpleNamespace(run=run, args=('sample_upgrade', False)))
        run.cancel()
        run.outcome = ([], '')
        run.finished.set()
        controller.poll()
        self.assertFalse(controller.idle())
        window._on_pipeline_complete.assert_not_called()
        controller.complete_subtask('sample_upgrade', False, 'safe cleanup complete')
        self.assertNotIn('sample_upgrade', app._pipeline_subtask_events)
        controller.poll()
        self.assertTrue(controller.idle())
        window._on_pipeline_complete.assert_called_once()

    def test_subtask_start_exception_completes_and_clears_ownership(self):
        from unittest.mock import Mock
        from src.ui.pipeline_ui import PipelineUiController
        app = SimpleNamespace(_pipeline_subtask_events={}, _pipeline_subtask_results={})
        app._begin_pipeline_subtask = lambda code: app._pipeline_subtask_events.setdefault(code, threading.Event())
        app._start_pipeline_sample_upgrade_on_ui = Mock(side_effect=ValueError('no start'))
        controller = PipelineUiController(app)
        self.addCleanup(controller.dispatcher.dispose)
        run = controller.channel.new_run()
        with self.assertRaisesRegex(ValueError, 'no start'):
            controller._start_subtask(SimpleNamespace(run=run,args=('sample_upgrade',False)))
        self.assertTrue(run.subtasks['sample_upgrade']['event'].is_set())
        self.assertNotIn('sample_upgrade', app._pipeline_subtask_events)

    def test_closing_completed_window_preserves_failed_channel_resume_token(self):
        from unittest.mock import Mock
        from line_check_assistant.pipeline_window import PipelineWindow
        from src.ui.tk_lifecycle import TkScope
        window = PipelineWindow.__new__(PipelineWindow)
        window._closed = False
        window._scope = TkScope()
        window._run = self.channel.new_run()
        window._run.finished.set()
        window.window = Mock()
        window.app = SimpleNamespace()
        for name in ('_check_vars', '_status_summary_vars', '_status_missing_vars', '_selection_controls', '_status_labels'):
            setattr(window, name, {})
        window._dispose()
        self.assertFalse(window._run.stop.is_set())
        self.assertTrue(window._run.detached)
        self.assertTrue(window._scope.closed)


if __name__ == '__main__':
    unittest.main()
